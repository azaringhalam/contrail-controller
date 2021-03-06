#!/usr/bin/env python

#
# Copyright (c) 2014 Juniper Networks, Inc. All rights reserved.
#

#
# analytics_stattest.py
#
# System tests for analytics
#

import sys
builddir = sys.path[0] + '/../..'
import threading
threading._DummyThread._Thread__stop = lambda x: 42
import signal
import gevent
from gevent import monkey
monkey.patch_all()
import os
import unittest
import testtools
import fixtures
import socket
from utils.analytics_fixture import AnalyticsFixture
from utils.stats_fixture import StatsFixture
from mockcassandra import mockcassandra
from mockredis import mockredis
import logging
import time
import pycassa
from pycassa.pool import ConnectionPool
from pycassa.columnfamily import ColumnFamily
from opserver.sandesh.viz.constants import *
from utils.opserver_introspect_utils import VerificationOpsSrv
from utils.util import retry
from collections import OrderedDict

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')


class StatsTest(testtools.TestCase, fixtures.TestWithFixtures):

    @classmethod
    def setUpClass(cls):
        if StatsTest._check_skip_test() is True:
            return

        if (os.getenv('LD_LIBRARY_PATH', '').find('build/lib') < 0):
            if (os.getenv('DYLD_LIBRARY_PATH', '').find('build/lib') < 0):
                assert(False)

        cls.cassandra_port = StatsTest.get_free_port()
        mockcassandra.start_cassandra(cls.cassandra_port)
        cls.redis_port = StatsTest.get_free_port()
        mockredis.start_redis(
            cls.redis_port, builddir+'/testroot/bin/redis-server')

    @classmethod
    def tearDownClass(cls):
        if StatsTest._check_skip_test() is True:
            return

        mockcassandra.stop_cassandra(cls.cassandra_port)
        mockredis.stop_redis(cls.redis_port)
        pass

    #@unittest.skip('Get samples using StatsOracle')
    def test_00_basicsamples(self):
        '''
        This test starts redis,vizd,opserver and qed
        It uses the test class' cassandra instance
        Then it sends test stats to the collector
        and checks if they can be accessed from QE.
        '''
        logging.info("*** test_00_basicsamples ***")
        if StatsTest._check_skip_test() is True:
            return True

        vizd_obj = self.useFixture(
            AnalyticsFixture(logging, builddir,
                             self.__class__.redis_port,
                             self.__class__.cassandra_port))
        assert vizd_obj.verify_on_setup()
        assert vizd_obj.verify_collector_obj_count()
        collectors = [vizd_obj.get_collector()]

        generator_obj = self.useFixture(
            StatsFixture("VRouterAgent", collectors,
                             logging, vizd_obj.get_opserver_port()))
        assert generator_obj.verify_on_setup()

        logging.info("Starting stat gen " + str(UTCTimestampUsec()))

        generator_obj.send_test_stat_dynamic("t00","samp1",1,1);
        generator_obj.send_test_stat_dynamic("t00","samp2",2,1.1);
        generator_obj.send_test_stat_dynamic("t00&t01","samp1&samp2",2,1.1);
        generator_obj.send_test_stat_dynamic("t00>t01>","samp1&samp2",2,1.1,
                                             "&test_s2>");

        logging.info("Checking Stats " + str(UTCTimestampUsec()))

        assert generator_obj.verify_test_stat("StatTable.TestStateDynamic.ts",
            "-2m", select_fields = [ "UUID", "ts.s1", "ts.i1", "ts.d1" ],
            where_clause = 'name="t00"', num = 2, check_rows =
            [{ "ts.s1":"samp2", "ts.i1":2, "ts.d1":1.1},
             { "ts.s1":"samp1", "ts.i1":1, "ts.d1":1}]);
        assert generator_obj.verify_test_stat("StatTable.TestStateDynamic.ts",
            "-2m", select_fields = [ "UUID", "ts.s1", "ts.s2" ],
            where_clause = 'name="t00&t01"', num = 1, check_rows =
            [{ "ts.s1":"samp1&samp2", "ts.s2": "" }])
        assert generator_obj.verify_test_stat("StatTable.TestStateDynamic.ts",
            "-2m", select_fields = [ "UUID", "name", "ts.s2" ],
            where_clause = 'ts.s1="samp1&samp2"', num = 2, check_rows =
            [{ "name":"t00&t01", "ts.s2": "" },
             { "name":"t00>t01>", "ts.s2":"&test_s2>" }])
            
        return True
    # end test_00_basicsamples

    #@unittest.skip('Get samples using StatsOracle')
    def test_01_statprefix(self):
        '''
        This test starts redis,vizd,opserver and qed
        It uses the test class' cassandra instance
        Then it sends test stats to the collector
        and checks if they can be accessed from QE, using prefix-suffix indexes
        '''
        logging.info("*** test_01_statprefix ***")
        if StatsTest._check_skip_test() is True:
            return True

        vizd_obj = self.useFixture(
            AnalyticsFixture(logging, builddir,
                             self.__class__.redis_port,
                             self.__class__.cassandra_port))
        assert vizd_obj.verify_on_setup()
        assert vizd_obj.verify_collector_obj_count()
        collectors = [vizd_obj.get_collector()]

        generator_obj = self.useFixture(
            StatsFixture("VRouterAgent", collectors,
                             logging, vizd_obj.get_opserver_port()))
        assert generator_obj.verify_on_setup()

        logging.info("Starting stat gen " + str(UTCTimestampUsec()))

        generator_obj.send_test_stat("t010","lxxx","samp1",1,1);
        generator_obj.send_test_stat("t010","lyyy","samp1",2,2);
        generator_obj.send_test_stat("t010","lyyy","samp3",2,2,"",5);
        generator_obj.send_test_stat("t010","lyyy&","samp3>",2,2,"");
        generator_obj.send_test_stat("t011","lyyy","samp2",1,1.1,"",7);
        generator_obj.send_test_stat("t011","lxxx","samp2",2,1.2);
        generator_obj.send_test_stat("t011","lxxx","samp2",2,1.2,"",9);
        generator_obj.send_test_stat("t010&t011","lxxx","samp2",1,1.4);
        generator_obj.send_test_stat("t010&t011","lx>ly","samp2",1,1.4);

        logging.info("Checking Stats str-str " + str(UTCTimestampUsec()))

        assert generator_obj.verify_test_stat("StatTable.StatTestState.st","-2m",
            select_fields = [ "UUID", "st.s1", "st.i1", "st.d1" ],
            where_clause = 'name|st.s1=t010|samp1', num = 2, check_rows =
            [{ "st.s1":"samp1", "st.i1":2, "st.d1":2},
             { "st.s1":"samp1", "st.i1":1, "st.d1":1}]);
        assert generator_obj.verify_test_stat("StatTable.StatTestState.st",
            "-2m", select_fields = [ "UUID", "l1" ], where_clause =
            'name|st.s1=t010&t011|samp2 OR name|st.s1=t010|samp3>',
            num = 3, check_rows = [{ "l1":"lxxx" }, { "l1":"lx>ly" },
            { "l1":"lyyy&" }])

        assert generator_obj.verify_test_stat("StatTable.StatTestState.st","-2m",
            select_fields = [ "UUID", "st.s1", "st.i1", "st.d1" ],
            where_clause = 'st.i1|st.i2=2|1<6', num = 1, check_rows =
            [{ "st.s1":"samp3", "st.i1":2, "st.d1":2}]);
        
        logging.info("Checking CLASS " + str(UTCTimestampUsec()))

        assert generator_obj.verify_test_stat("StatTable.StatTestState.st","-2m",
            select_fields = [ "T", "name", "l1", "CLASS(T)" ],
            where_clause = 'name=*', num = 9, check_uniq =
            { "CLASS(T)":7 })
         
        return True
    # end test_01_statprefix

    #@unittest.skip('Get samples using StatsOracle')
    def test_02_overflowsamples(self):
        '''
        This test starts redis,vizd,opserver and qed
        It uses the test class' cassandra instance
        Then it sends test stats to the collector
        and checks if they can be accessed from QE.
        '''
        logging.info("*** test_02_overflowsamples ***")
        if StatsTest._check_skip_test() is True:
            return True

        vizd_obj = self.useFixture(
            AnalyticsFixture(logging, builddir,
                             self.__class__.redis_port,
                             self.__class__.cassandra_port))
        assert vizd_obj.verify_on_setup()
        assert vizd_obj.verify_collector_obj_count()
        collectors = [vizd_obj.get_collector()]

        generator_obj = self.useFixture(
            StatsFixture("VRouterAgent", collectors,
                             logging, vizd_obj.get_opserver_port()))
        assert generator_obj.verify_on_setup()

        logging.info("Starting stat gen " + str(UTCTimestampUsec()))

        generator_obj.send_test_stat_dynamic("t02","samp02-2",0xffffffffffffffff,1.1);

        logging.info("Checking Stats " + str(UTCTimestampUsec()))

        assert generator_obj.verify_test_stat("StatTable.TestStateDynamic.ts",
            "-2m", select_fields = [ "UUID", "ts.s1", "ts.i1", "ts.d1" ],
            where_clause = 'name="t02"', num = 1, check_rows =
            [{"ts.s1":"samp02-2", "ts.i1":0xffffffffffffffff, "ts.d1":1.1}])
            
        return True
    # end test_02_overflowsamples

    #@unittest.skip('Get samples using StatsOracle')
    def test_03_ipfix(self):
        '''
        This test starts redis,vizd,opserver and qed
        It uses the test class' cassandra instance
        Then it feeds IPFIX packets to the collector
        and queries for them
        '''
        logging.info("*** test_03_ipfix ***")
        if StatsTest._check_skip_test() is True:
            return True
        
        vizd_obj = self.useFixture(
            AnalyticsFixture(logging, builddir,
                             self.__class__.redis_port,
                             self.__class__.cassandra_port,
                             ipfix_port = True))
        assert vizd_obj.verify_on_setup()
        assert vizd_obj.verify_collector_obj_count()
        ipfix_port = vizd_obj.collectors[0].get_ipfix_port()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        UDP_IP = "127.0.0.1"
        f1 = open(builddir + '/opserver/test/data/ipfix_t.data')
        sock.sendto(f1.read(), (UDP_IP, ipfix_port))
        f2 = open(builddir + '/opserver/test/data/ipfix_d.data')
        sock.sendto(f2.read(), (UDP_IP, ipfix_port))
        sock.close()

        logging.info("Verifying IPFIX data sent to port %s" % str(ipfix_port))
        uexp = {u'name': u'127.0.0.1',
               u'flow.sport': 49152,
               u'flow.sip': u'10.84.45.254',
               u'flow.flowtype': u'IPFIX'}
        vns = VerificationOpsSrv('127.0.0.1', vizd_obj.get_opserver_port())
        assert(self.verify_ipfix(vns,uexp))

        return True
    # end test_03_ipfix

    #@unittest.skip('Get minmax values from inserted stats')
    def test_04_min_max_query(self):
        '''
        This test starts redis,vizd,opserver and qed
        It uses the test class' cassandra instance
        Then it inserts into the stat table rows 
        and queries MAX and MIN on them
        '''
        logging.info("*** test_04_min_max_query ***")
        if StatsTest._check_skip_test() is True:
            return True
        vizd_obj = self.useFixture(
            AnalyticsFixture(logging, builddir,
                             self.__class__.redis_port,
                             self.__class__.cassandra_port))
        assert vizd_obj.verify_on_setup()
        assert vizd_obj.verify_collector_obj_count()
        collectors = [vizd_obj.get_collector()]

        generator_obj = self.useFixture(
            StatsFixture("VRouterAgent", collectors,
                             logging, vizd_obj.get_opserver_port()))
        assert generator_obj.verify_on_setup()

        logging.info("Starting stat gen " + str(UTCTimestampUsec()))

        generator_obj.send_test_stat("t04","lxxx","samp1",1,5);
        generator_obj.send_test_stat("t04","lyyy","samp1",4,3.4);
        generator_obj.send_test_stat("t04","lyyy","samp1",2,4,"",5);

        logging.info("Checking Stats " + str(UTCTimestampUsec()))
        assert generator_obj.verify_test_stat("StatTable.StatTestState.st","-2m",
            select_fields = [ "MAX(st.i1)"],
            where_clause = 'name|st.s1=t04|samp1', num = 1, check_rows =
            [{u'MAX(st.i1)': 4}]);

        assert generator_obj.verify_test_stat("StatTable.StatTestState.st","-2m",
            select_fields = [ "MIN(st.d1)"],
            where_clause = 'name|st.s1=t04|samp1', num = 1, check_rows =
            [{u'MIN(st.d1)': 3.4}]);

        return True
    # end test_04_overflowsamples

    @retry(delay=1, tries=5)
    def verify_ipfix(self, vns, uexp):
        logging.info("Trying to verify IPFIX...")
        res = vns.post_query("StatTable.UFlowData.flow",
            start_time="-5m", end_time="now",
            select_fields=["name", "flow.flowtype", "flow.sip", "flow.sport"],
            where_clause = 'name=*')
        logging.info("Result: " + str(res))
        if len(res)!=1:
            return False
        exp = OrderedDict(sorted(uexp.items(), key=lambda t: t[0]))
        rs = OrderedDict(sorted(res[0].items(), key=lambda t: t[0]))
        if exp != rs:
            return False
        return True

    @staticmethod
    def get_free_port():
        cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cs.bind(("", 0))
        cport = cs.getsockname()[1]
        cs.close()
        return cport

    @staticmethod
    def _check_skip_test():
        if (socket.gethostname() == 'build01'):
            logging.info("Skipping test")
            return True
        return False

def _term_handler(*_):
    raise IntSignal()

if __name__ == '__main__':
    gevent.signal(signal.SIGINT,_term_handler)
    unittest.main(catchbreak=True)
