import os
from setuptools import setup

try:
    from ovos_config import LocalConf
    from ovos_config.locations import USER_CONFIG
    config = LocalConf(USER_CONFIG)
except ImportError:
    config = None


BASEDIR = os.path.abspath(os.path.dirname(__file__))
PLUGIN_ENTRY_POINT = 'hivemind_nodered_plug = hivemind_PHAL_plugin_nodered.node:NodeRedMind'
SKILL_ENTYRY_POINT = 'hivemind_nodered_skill = hivemind_PHAL_plugin_nodered.skill:NodeRedSkill'


def get_version():
    """ Find the version of the package"""
    version = None
    version_file = os.path.join(BASEDIR, 'hivemind_PHAL_plugin_nodered', 'version.py')
    major, minor, build, alpha = (None, None, None, None)
    with open(version_file) as f:
        for line in f:
            if 'VERSION_MAJOR' in line:
                major = line.split('=')[1].strip()
            elif 'VERSION_MINOR' in line:
                minor = line.split('=')[1].strip()
            elif 'VERSION_BUILD' in line:
                build = line.split('=')[1].strip()
            elif 'VERSION_ALPHA' in line:
                alpha = line.split('=')[1].strip()

            if ((major and minor and build and alpha) or
                    '# END_VERSION_BLOCK' in line):
                break
    version = f"{major}.{minor}.{build}"
    if alpha and int(alpha) > 0:
        version += f"a{alpha}"
    return version


def package_files(directory):
    paths = []
    for (path, directories, filenames) in os.walk(directory):
        for filename in filenames:
            paths.append(os.path.join('..', path, filename))
    return paths


def required(requirements_file):
    """ Read requirements file and remove comments and empty lines. """
    with open(os.path.join(BASEDIR, requirements_file), 'r') as f:
        requirements = f.read().splitlines()
        if 'MYCROFT_LOOSE_REQUIREMENTS' in os.environ:
            print('USING LOOSE REQUIREMENTS!')
            requirements = [r.replace('==', '>=').replace('~=', '>=') for r in requirements]
        return [pkg for pkg in requirements
                if pkg.strip() and not pkg.startswith("#")]


setup(
    name='hivemind_PHAL_plugin_nodered',
    version=get_version(),
    description='OVOS hivemind PHAL plugin for Node-Red',
    url='https://github.com/emphasize/hivemind_PHAL_plugin_nodered',
    author='emphasize',
    author_email='',
    license='Apache-2.0',
    packages=['hivemind_PHAL_plugin_nodered'],
    install_requires=required("requirements/requirements.txt"),
    package_data={'': package_files('hivemind_PHAL_plugin_nodered')},
    include_package_data=True,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Text Processing :: Linguistic',
        'License :: OSI Approved :: Apache Software License',

        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    entry_points={
        'ovos.plugin.phal': PLUGIN_ENTRY_POINT,
        'ovos.plugin.skill': SKILL_ENTYRY_POINT
    }
)


if config is not None:
    config.merge(
        {
            "PHAL": {
                "hivemind_PHAL_plugin_nodered": {
                    "ssl": False,
                    "blacklist" : {
                        "messages": [],
                        "skills": [],
                        "intents": []
                    }
                }
            }
        }
    )
    config.store()