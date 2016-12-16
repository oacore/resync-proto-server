#!/usr/bin/env python
# encoding: utf-8
"""

resync-proto-server: ResourceSync tool for exposing a changing Web data source.

Created by Giorgio Basile on 2016-12-12
Based on the resync-simulator project: https://github.com/resync/resync-simulator
"""
import sys
import optparse

import yaml
import logging
import logging.config

import logutils.dictconfig

from resyncserver._version import __version__
from resyncserver.changememory import DynamicChangeList
from resyncserver.http import HTTPInterface
from resyncserver.source import Source
from resyncserver.source import DynamicResourceListBuilder

DEFAULT_CONFIG_FILE = 'config/default.yaml'
DEFAULT_LOG_FILE = 'config/logging.yaml'


def main():

    # Define simulator options
    parser = optparse.OptionParser(description="ResourceSync Server",
                                   usage='usage: %prog [options]  (-h for help)',
                                   version='%prog '+__version__)
    parser.add_option('--config-file', '-c',
                      help="the simulation configuration file")
    parser.add_option('--log-config', '-l',
                      default=DEFAULT_LOG_FILE,
                      help="the logging configuration file")
    parser.add_option('--port', '-p', type=int,
                      default=8888,
                      help="the HTTP interface port that the server will run on")
    parser.add_option('--base-uri', '-b',
                      default='',
                      help="the base URI where the simulator is running (defaults to localhost:port)")
    parser.add_option('--folder', '-f',
                      help="the local folder to be exposed")
    #parser.add_option('--pub-server', '-s',
                      #help="publish server address for PubSubHubbub")

    # Parse command line arguments
    (args, clargs) = parser.parse_args()


    if (len(clargs) > 0):
        parser.print_help()
        return
    if (args.config_file is None):
        parser.print_help()
        return

    # Load the logging configuration file and set up logging
    logconfig = yaml.load(open(args.log_config, 'r'))
    if sys.version_info >= (2, 7):
        # this stuff requires 2.7
        logging.config.dictConfig(logconfig)
    else:
        logutils.dictconfig.dictConfig(logconfig)
        pass

    # Load the YAML configuration file
    config = yaml.load(open(args.config_file, 'r'))

    # Set up the source
    source_settings = config['source']
    base_uri = args.base_uri
    if base_uri == '':
        base_uri = 'http://localhost:' + str(args.port)
        #base_uri = "http://" + socket.gethostname() + ":" + str(args.port)

    source = Source(source_settings, base_uri, args.port)

    # Set up and register the source resource_list
    source.add_resource_list_builder(DynamicResourceListBuilder(source, config['resource_list_builder']))

    # Set up and register change memory
    source.add_changememory(DynamicChangeList(source, config['changememory']))

    # Bootstrap the source
    source.bootstrap()

    # Start the Web interface, run the simulation
    # Attach HTTP interface to source
    http_interface = HTTPInterface(source)
    try:
        http_interface.start()
        print "ResourceSync server started on port " + str(args.port)
        source.watch_folder()
    except KeyboardInterrupt:
        print("Exiting gracefully...")
    finally:
        http_interface.stop()

if __name__ == '__main__':
    main()
