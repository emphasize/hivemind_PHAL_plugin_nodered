import time

from ovos_bus_client import Message
from ovos_bus_client.message import dig_for_message
from ovos_utils.intents import IntentBuilder
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.decorators import intent_handler, intent_file_handler
from ovos_workshop.skills.fallback import FallbackSkill
from ovos_utils.process_utils import RuntimeRequirements
from ovos_utils import classproperty, create_daemon


class NodeRedSkill(FallbackSkill):
    def __init__(self):
        super(NodeRedSkill, self).__init__(name='NodeRedSkill')
        # can not reload, twisted reactor can not be restarted
        self.reload_skill = False            
        self.waiting_for_node = False
        self.conversing = False
        self._error = None
    
    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=False,
                                   requires_internet=False,
                                   requires_network=True,
                                   no_internet_fallback=True,
                                   no_network_fallback=False)

    def initialize(self):

        if "timeout" not in self.settings:
            self.settings["timeout"] = 15
        if "priority" not in self.settings:
            self.settings["priority"] = 50
            
        # TODO pass these to hivemind / settingsmeta
        # if "ip_list" not in self.settings:
        #     self.settings["ip_list"] = []
        # if "ip_blacklist" not in self.settings:
        #     self.settings["ip_blacklist"] = True

        self.register_fallback(self.handle_fallback,
                               int(self.settings["priority"]))

        self.add_event("node_red.success", self.handle_node_success)
        self.add_event("node_red.intent_failure", self.handle_node_failure)
        self.add_event("node_red.converse.activate",
                       self.handle_converse_enable)
        self.add_event("node_red.converse.deactivate",
                       self.handle_converse_disable)
        self.add_event("hive.client.connection.error",
                       self.handle_wrong_key)
        self.converse_thread = create_daemon(self.converse_keepalive)

    @intent_handler(IntentBuilder("WhyRebootIntent")
                         .require("WhyKeyword").require("KEY_CHANGED"))
    def handle_why_reboot(self, message):
        self.speak_dialog("why", wait=True)

    def handle_wrong_key(self, message):

        error = message.data.get("error")
        if self._error is None or error != self._error:
            self.speak_dialog("bad_key")
            self.speak(error)
        self._error = error

    def get_intro_message(self):
        # welcome dialog on skill install
        self.speak_dialog("intro")

    # node red control intents
    @intent_file_handler("pingnode.intent")
    def handle_ping_node(self, message):
        self.speak("ping")

        def pong(message):
            self.speak("pong")

        self.bus.once("node_red.pong", pong)

        message = message.forward("node_red.ping")
        self.bus.emit(message)

    @intent_file_handler("converse.enable.intent")
    def handle_converse_enable(self, message):
        if self.conversing:
            self.speak_dialog("converse_on")
        else:
            self.speak_dialog("converse_enable")
            self.conversing = True

    @intent_file_handler("converse.disable.intent")
    def handle_converse_disable(self, message):
        if not self.conversing:
            self.speak_dialog("converse_off")
        else:
            self.speak_dialog("converse_disable")
            self.conversing = False
    
    # node red event handlers
    def handle_node_success(self, message):
        self.waiting_for_node = False
        self.success = True

    def handle_node_failure(self, message):
        self.waiting_for_node = False
        self.success = False

    def wait_for_node(self):
        start = time.time()
        self.success = False
        self.waiting_for_node = True
        while self.waiting_for_node and \
                time.time() - start < float(self.settings["timeout"]):
            time.sleep(0.1)
        if self.waiting_for_node:
            message = dig_for_message()
            if not message:
                message = Message("node_red.timeout")
            else:
                message.reply("node_red.timeout")
            self.bus.emit(message)
            self.waiting_for_node = False
        return self.success

    # converse
    def converse_keepalive(self):
        while True:
            if self.conversing:
                # avoid converse timed_out
                self.make_active()
            time.sleep(60)

    def converse(self, utterances, lang="en-us"):
        if self.conversing:
            message = dig_for_message()
            if message:
                message = message.reply("node_red.converse",
                                        {"utterance": utterances[0]})
            else:
                message = Message("node_red.converse",
                                  {"utterance": utterances[0]})

            if not message.context.get("platform", "").startswith("NodeRedMind"):
                self.bus.emit(message)
                return self.wait_for_node()
        return False

    # fallback
    def handle_fallback(self, message):
        message = message.reply("node_red.fallback", message.data)
        self.bus.emit(message)
        return self.wait_for_node()
    
    def shutdown(self):
        if self.converse_thread.is_alive():
            self.converse_thread.join(2)
        super(NodeRedSkill, self).shutdown()


def create_skill():
    return NodeRedSkill()