#!/usr/bin/env python
# encoding: utf-8
"""
source.py: A source holds a set of resources and changes over time.

Resources are internally stored by their basename (e.g., 1) for memory
efficiency reasons.

Created by Bernhard Haslhofer on 2012-04-24.
Edited by Giorgio Basile on 2016-12-12.
"""

import os
import random
import pprint
import logging
import time
import urllib
import urlparse
from os.path import basename


from resync.utils import compute_md5_for_file
from resync.resource_list import ResourceList

from resyncserver.observer import Observable
from resyncserver.resource import Resource

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# Source-specific capability implementations

class DynamicResourceListBuilder(object):
    """Generates an resource_list snapshot from a source."""

    def __init__(self, source, config):
        """Initialize the DynamicResourceListBuilder."""
        self.source = source
        self.config = config
        self.logger = logging.getLogger('resource_list_builder')

    def bootstrap(self):
        """Bootstrapping procedures implemented in subclasses."""
        pass

    @property
    def path(self):
        """The resource_list path from the config file."""
        return self.config['uri_path']

    @property
    def uri(self):
        """The resource_list URI.

        e.g., http://localhost:8080/resourcelist.xml
        """
        return self.source.base_uri + "/" + self.path

    def generate(self):
        """Generate a resource_list (snapshot from the source)."""
        then = time.time()
        resource_list = ResourceList(
            resources=self.source.resources, count=self.source.resource_count)
        now = time.time()
        self.logger.info("Generated resource_list: %f" % (now - then))
        return resource_list


class Source(Observable, FileSystemEventHandler):
    """A source contains a list of resources and changes over time."""

    RESOURCE_PATH = "/resources"  # to append to base_uri
    STATIC_FILE_PATH = os.path.join(os.path.dirname(__file__), "static")

    def __init__(self, config, base_uri, port):
        """Initalize the source."""
        super(Source, self).__init__()
        self.logger = logging.getLogger('source')
        self.config = config
        self.logger.info("Source config: %s " % self.config)
        self.port = port
        self.base_uri = base_uri
        self.max_res_id = 1
        self._repository = {}  # {basename, {timestamp, length}}
        self.resource_list_builder = None  # builder implementation
        self.changememory = None  # change memory implementation
        self.no_events = 0
        self.folder = self.config['folder']
        #self.pub_server = self.config['pub_server']

    # Source capabilities

    def add_resource_list_builder(self, resource_list_builder):
        """Add a resource_list builder implementation."""
        self.resource_list_builder = resource_list_builder

    @property
    def has_resource_list_builder(self):
        """Return True if the Source has an resource_list builder."""
        return bool(self.resource_list_builder is not None)

    def add_changememory(self, changememory):
        """Add a changememory implementation."""
        self.changememory = changememory

    @property
    def has_changememory(self):
        """Return True if a source maintains a change memory."""
        return bool(self.changememory is not None)

    # Bootstrap Source

    def bootstrap(self):
        """Bootstrap the source with a set of resources."""
        self.logger.info("Bootstrapping source...")
        self._folder_boot(self.folder)
        if self.has_changememory:
            self.changememory.bootstrap()
        if self.has_resource_list_builder:
            self.resource_list_builder.bootstrap()
        self._log_stats()

    def bootstrap_simulator(self):
        """Bootstrap the source with a set of resources."""
        self.logger.info("Bootstrapping source...")
        for i in range(self.config['number_of_resources']):
            self._create_resource(notify_observers=False)
        if self.has_changememory:
            self.changememory.bootstrap()
        if self.has_resource_list_builder:
            self.resource_list_builder.bootstrap()
        self._log_stats()

    def _folder_boot(self, cur_folder):
        files_names = os.listdir(cur_folder)
        for f in files_names:
            f_path = os.path.join(cur_folder, f)
            if os.path.isdir(f_path):
                self._folder_boot(f_path)
            else:
                if not basename(f_path).startswith('.'):
                    resource_subpath = os.path.relpath(f_path, self.folder)
                    self._create_resource(resource_subpath, f_path, notify_observers=False)

    # Source data accessors

    @property
    def describedby_uri(self):
        """Description of Source, here assume base_uri."""
        return self.base_uri

    @property
    def source_description_uri(self):
        """URI of Source Description document.

        Will use standard pattern for well-known URI unless
        an explicit configuration is given.
        """
        if ('source_description_uri' in self.config):
            return self.config['source_description_uri']
        return self.base_uri + '/.well-known/resourcesync'

    @property
    def capability_list_uri(self):
        """URI of Capability List Document."""
        return self.base_uri + '/capabilitylist.xml'

    @property
    def resource_count(self):
        """The number of resources in the source's repository."""
        return len(self._repository)

    @property
    def resources(self):
        """Iterate over resources and yields resource objects."""
        repository = self._repository
        for basename in repository.keys():
            resource = self.resource(basename)
            if resource is None:
                self.logger.error("Cannot create resource %s " % basename +
                                  "because source object has been deleted.")
            yield resource

    @property
    def random_resource(self):
        """Return a single random resource."""
        rand_res = self.random_resources()
        if len(rand_res) == 1:
            return rand_res[0]
        else:
            return None

    def resource(self, basename):
        """Create and return a resource object.

        Details of the resource with basename are taken from the
        internal resource repository. Repository values are copied
        into the object.
        """
        if basename not in self._repository:
            return None
        uri = urllib.quote(urlparse.urljoin(self.base_uri, os.path.join(Source.RESOURCE_PATH, basename)), safe='/:')
        timestamp = self._repository[basename]['timestamp']
        length = self._repository[basename]['length']
        md5 = self._repository[basename]['md5']
        return Resource(uri=uri, timestamp=timestamp, length=length,
                        md5=md5)

    def resource_payload(self, basename, length=None):
        """Generate dummy payload by repeating res_id x length times."""
        if length is None:
            length = self._repository[basename]['length']
        no_repetitions = length // len(basename)
        content = "".join([basename for x in range(no_repetitions)])
        no_fill_chars = length % len(basename)
        fillchars = "".join(["x" for x in range(no_fill_chars)])
        return content + fillchars

    def random_resources(self, number=1):
        """Return a random set of resources, at most all resources."""
        if number > len(self._repository):
            number = len(self._repository)
        rand_basenames = random.sample(self._repository.keys(), number)
        return [self.resource(basename) for basename in rand_basenames]

    # Private Methods

    def _create_resource(self, basename=None, file_path=None, notify_observers=True):
        """Create a new resource, add it to the source, notify observers."""
        payload = open(file_path).read()
        md5 = compute_md5_for_file(file_path)
        self._repository[basename] = {'timestamp': os.path.getmtime(file_path), 'length': len(payload), 'md5': md5}
        if notify_observers:
            change = Resource(
                resource=self.resource(basename), change="created")
            self.notify_observers(change)

    def _update_resource(self, basename, file_path=None):
        """Update a resource, notify observers."""
        self._delete_resource(basename, notify_observers=False)
        self._create_resource(basename, file_path, notify_observers=False)
        change = Resource(
            resource=self.resource(basename), change="updated")
        self.notify_observers(change)

    def _delete_resource(self, basename, notify_observers=True):
        """Delete a given resource, notify observers."""
        res = self.resource(basename)
        del self._repository[basename]
        res.timestamp = time.time()
        if notify_observers:
            change = Resource(
                uri=res.uri, timestamp=res.timestamp, change="deleted")
            self.notify_observers(change)

    def _log_stats(self):
        """Output current source statistics via the logger."""
        stats = {
            'no_resources': self.resource_count,
            'no_events': self.no_events
        }
        self.logger.info("Source stats: %s" % stats)

    def __str__(self):
        """Print out the source's resources."""
        return pprint.pformat(self._repository)

        # watchdog!

    def watch_folder(self):
        observer = Observer()
        observer.schedule(self, self.folder, recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    def process(self, event):
        """
        event.event_type
            'modified' | 'created' | 'moved' | 'deleted'
        event.is_directory
            True | False
        event.src_path
            path/to/observed/file
        """
        if event.src_path == self.folder:
            pass
        elif event.is_directory:
            if event.event_type == 'created':
                print "Detected creation of directory " + basename(event.src_path)
            elif event.event_type == 'modified':
                print "Detected update of directory " + basename(event.src_path)
            elif event.event_type == 'deleted':
                print "Detected deletion of directory " + basename(event.src_path)
        elif not event.is_directory:
            if basename(event.src_path) != '.DS_Store':
                if event.event_type == 'created':
                    self._create_resource(os.path.relpath(event.src_path, self.folder), event.src_path)
                    print basename(event.src_path) + " created"
                elif event.event_type == 'modified':
                    self._update_resource(os.path.relpath(event.src_path, self.folder), event.src_path)
                    print basename(event.src_path) + " updated"
                elif event.event_type == 'deleted':
                    self._delete_resource(os.path.relpath(event.src_path, self.folder))
                    print basename(event.src_path) + " deleted"
                elif event.event_type == 'moved':
                    self._create_resource(os.path.relpath(event.dest_path, self.folder), event.dest_path)
                    self._delete_resource(os.path.relpath(event.src_path, self.folder))
                    print event.src_path + " moved to " + event.dest_path


    def on_modified(self, event):
        self.process(event)

    def on_created(self, event):
        self.process(event)

    def on_deleted(self, event):
        self.process(event)

    def on_moved(self, event):
        self.process(event)

