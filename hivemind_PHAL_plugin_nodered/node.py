import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from ovos_plugin_manager.phal import PHALPlugin
from ovos_bus_client.message import Message
from ovos_utils.process_utils import RuntimeRequirements
from ovos_utils.log import LOG
from ovos_config.locations import xdg_data_home
from tornado import web
from hivemind_bus_client.message import HiveMessage
from hivemind_core.protocol import (
    HiveMindListenerProtocol,
    HiveMindListenerInternalProtocol,
    HiveMindClientConnection
)
from hivemind_core.database import ClientDatabase
from hivemind_core.service import (
    MessageBusEventHandler,
    create_self_signed_cert
)
from ovos_utils import classproperty


ROUTING_MSG = ["node_red.answer",
               "node_red.speak",
               "node_red.query",
               "node_red.tts",
               "node_red.converse.activate",
               "node_red.converse.deactivate",
               "node_red.intent_failure",
               "node_red.pong",
               "node_red.listen"]


class NodeRedMind(PHALPlugin):

    def __init__(self, bus=None, config=None):
        super().__init__(bus=bus, name="ovos-PHAL-plugin-cec", config=config)

        self.host = self.config.get('host', '127.0.0.1')
        self.port = self.config.get('port', 6789)
        route = "/"

        self.protocol = NodeRedListenerProtocol()
        self.protocol.bind(MessageBusEventHandler, self.bus)
        self.use_ssl = self.config.get("ssl", False)
        # if self.config.get("use_ssl"):
        #     self.protocol.load_ssl_config(self.config)

        routes = [(route, MessageBusEventHandler)]
        self.listener = web.Application(routes)
        
        self.start_mind()
    
    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=False,
                                   requires_internet=False,
                                   requires_network=True,
                                   no_internet_fallback=True,
                                   no_network_fallback=False)
    
    @property
    def ssl_opts(self):
        cert_dir = self.config.get("cert_dir", f"{xdg_data_home()}/hivemind")
        cert_name = self.config.get("cert_name", "nodered")
        CERT_FILE = f"{cert_dir}/{cert_name}.crt"
        KEY_FILE = f"{cert_dir}/{cert_name}.key"
        if not os.path.isfile(CERT_FILE):
            create_self_signed_cert(cert_dir, cert_name)

        return {"certfile": CERT_FILE,
                "keyfile": KEY_FILE}
    
    def start_mind(self):
        self.handle_credentials()
        if self.use_ssl:
            self.listener.listen(self.port, self.host, ssl_options=self.ssl_opts)
        else:
            self.listener.listen(self.port, self.host)
    
    def handle_credentials(self):
        user = self.config.get("username", "nodered")
        if not ClientDatabase().get_clients_by_name(user):
            blacklist = self.config.get("blacklist", dict())
            password = self.config.get("password", os.urandom(16).hex())
            access_key = self.config.get("access_key", os.urandom(16).hex())

            ClientDatabase().add_client(user,
                                        key=access_key,
                                        blacklist=blacklist,
                                        password=password)
            LOG.info(f"Created new user: {user}, pw:{password}, key:{access_key}")
    
    def shutdown(self):
        super().shutdown()
        self.join()


class NodeRedListenerProtocol(HiveMindListenerProtocol):

    def __init__(self, debug=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = debug
        self.zero = None
        self.upnp_server = None
        self.ssdp = None

    # parsed protocol messages
    def nodered_send(self, message):
        if isinstance(message, Message):
            payload = json.dumps({'msg_type': message.msg_type,
                                  'data': message.data,
                                  'context': message.context})
        elif isinstance(message, dict):
            payload = repr(json.dumps(message))
        else:
            payload = message

        LOG.info(payload)
        for peer in set(self.clients):
            client: HiveMindClientConnection = self.clients[peer]["instance"]
            client.send(payload.encode())


    # HiveMind protocol messages -  from node red
    def handle_message(self,
                       message: HiveMessage,
                       client: HiveMindClientConnection):
        """
       Process message from client, decide what to do internally here
       """
        #client_protocol, ip, sock_num = self.client.peer.split(":")

        if isinstance(message, HiveMessage):
            data = message.as_dict.get("payload", dict())
        else:
            _msg = json.loads(message)
            data = _msg.get("payload", dict())

        msg_type = data.get("msg_type", "") or data.get("type", "")

        if msg_type.startswith("node_red."):
            data["context"]["source"] = client.peer
            data["context"]["platform"] = "platform"
            if msg_type == 'node_red.query':
                msg_type = "recognizer_loop:utterance"
                data["context"]["destination"] = "skills"
            elif msg_type in ['node_red.answer', 'node_red.speak']:
                msg_type = "speak"
            elif msg_type  == 'node_red.tts':
                msg_type = "speak"
                data["context"]["destination"] = ["audio"]
            elif msg_type == 'node_red.listen':
                msg_type = "mycroft.mic.listen"
                data["context"]["destination"] = ["audio"]
            elif msg_type in ROUTING_MSG:
                data["context"]["destination"] = None
            else:
                data["context"]["destination"] = "skills"
            
            self.handle_inject_mycroft_msg(Message(msg_type,
                                                   data["data"],
                                                   data["context"]), client)
            
            if msg_type in ['node_red.answer', 'node_red.speak', 'node_red.tts']:
                self.handle_inject_mycroft_msg(Message("node_red.success",
                                                       data["data"],
                                                       data["context"]), client)
        else:
            super().handle_message(message, client)

    def handle_bus_message(self, payload, client):
        # Generate mycroft Message
        super().handle_bus_message(payload, client)
        # echo to nodered (all connections/flows)
        # TODO skip source peer
        self.nodered_send(message=Message("hivemind.bus", payload))

    def handle_broadcast_message(self, data, client):
        payload = data["payload"]

        LOG.info("Received broadcast message at: ")
        LOG.debug("ROUTE: " + str(data["node"]))
        LOG.debug("PAYLOAD: " + str(payload))
        # echo to nodered (all connections/flows)
        # TODO skip source peer
        self.nodered_send(message=Message("hivemind.broadcast", payload))

    def handle_propagate_message(self, data, client):

        payload = data["payload"]

        LOG.info("Received propagate message at: ")
        LOG.debug("ROUTE: " + str(data["node"]))
        LOG.debug("PAYLOAD: " + str(payload))

        # echo to nodered (all connections/flows)
        # TODO skip source peer
        self.nodered_send(message=Message("hivemind.propagate", payload))

    def handle_escalate_message(self, data, client):
        payload = data["payload"]

        LOG.info("Received escalate message at: ")
        LOG.debug("ROUTE: " + str(data["node"]))
        LOG.debug("PAYLOAD: " + str(payload))

        # echo to nodered (all connections/flows)
        # TODO skip source peer
        self.nodered_send(message=Message("hivemind.escalate", payload))

    # from mycroft bus
    def handle_outgoing_mycroft(self, message=None):
        if not message:
            return LOG.error("No message to send")
            
        if isinstance(message, dict):
            message = json.dumps(message)
        if isinstance(message, str):
            message = Message.deserialize(message)
        if message.msg_type == "complete_intent_failure":
            message.msg_type = "hive.complete_intent_failure"

        message.context = message.context or {}
        peer = message.context.get("destination")
        
        # if msg_type namespace is node_red
        if message.msg_type.startswith("play:query"):
           LOG.debug(message.serialize())
        # if message is for a node red connection, forward
        if message.msg_type.startswith("node_red."):
            self.nodered_send(message)
        return
