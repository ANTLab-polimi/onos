 #!/usr/bin/python

from mininet.cli import CLI
from mininet.log import info, debug, setLogLevel
from mininet.net import Mininet
from mininet.node import Host, RemoteController
from mininet.topo import Topo
import os, subprocess, distutils.spawn, socket, json, glob, urllib2, base64, time
import create_abilene_conf as abilene
import cPickle as pickle
import threading
import time

QUAGGA_DIR = '/usr/lib/quagga'
# Must exist and be owned by quagga user (quagga:quagga by default on Ubuntu)
QUAGGA_RUN_DIR = '/var/run/quagga'
CONFIG_DIR = 'configs'
CONFIG_DIR_ABILENE = 'configs-abilene'

def is_installed(name):
    return distutils.spawn.find_executable(name) is not None

if not is_installed('iperf3'):
    subprocess.call("sudo apt-get -q -y install iperf3".split())

def json_GET_req(url):
    try:
        request = urllib2.Request(url)
        base64string = base64.encodestring('%s:%s' % ('onos', 'rocks')).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        response = urllib2.urlopen(request)
        return json.loads(response.read())
    except IOError as e:
        print e
        return ""

class ExecuteCommands(threading.Thread):
    def __init__(self, host, cmd_list, event):
        threading.Thread.__init__(self)
        self.host = host
        self.cmd_list = cmd_list
        self.event = event

    def run(self):
        self.event.wait()
        for cmd in self.cmd_list:
            self.host.pexec(cmd)


class SdnIpHost(Host):
    def __init__(self, name, ip, route, *args, **kwargs):
        Host.__init__(self, name, ip=ip, *args, **kwargs)

        self.route = route

    def config(self, **kwargs):
        Host.config(self, **kwargs)

        debug("configuring route %s" % self.route)

        self.cmd('ip route add default via %s' % self.route)

class Router(Host):
    def __init__(self, name, quaggaConfFile, zebraConfFile, intfDict, *args, **kwargs):
        Host.__init__(self, name, *args, **kwargs)

        self.quaggaConfFile = quaggaConfFile
        self.zebraConfFile = zebraConfFile
        self.intfDict = intfDict

    def config(self, **kwargs):
        Host.config(self, **kwargs)
        self.cmd('sysctl net.ipv4.ip_forward=1')

        for intf, attrs in self.intfDict.items():
            self.cmd('ip addr flush dev %s' % intf)
            if 'mac' in attrs:
                self.cmd('ip link set %s down' % intf)
                self.cmd('ip link set %s address %s' % (intf, attrs['mac']))
                self.cmd('ip link set %s up ' % intf)
            for addr in attrs['ipAddrs']:
                self.cmd('ip addr add %s dev %s' % (addr, intf))

        self.cmd('/usr/lib/quagga/zebra -d -f %s -z %s/zebra%s.api -i %s/zebra%s.pid' % (self.zebraConfFile, QUAGGA_RUN_DIR, self.name, QUAGGA_RUN_DIR, self.name))
        self.cmd('/usr/lib/quagga/bgpd -d -f %s -z %s/zebra%s.api -i %s/bgpd%s.pid' % (self.quaggaConfFile, QUAGGA_RUN_DIR, self.name, QUAGGA_RUN_DIR, self.name))


    def terminate(self):
        self.cmd("ps ax | egrep 'bgpd%s.pid|zebra%s.pid' | awk '{print $1}' | xargs kill" % (self.name, self.name))

        Host.terminate(self)


class AbileneTopo( Topo ):
    "Abilene topology"

    def build( self ):
        switches = {}
        for x, node in enumerate(abilene.nodes):
            switches['s%d' % (x+1)] = self.addSwitch('s%d' % (x+1), dpid='00000000000000%0.2x' % (0xa0+x+1))

        zebraConf = '%s/zebra.conf' % CONFIG_DIR_ABILENE

        for i in range(1, len(switches)+1):
            name = 'r%s' % i

            eth0 = { 'mac' : '00:00:00:00:0%s:01' % i,
                     'ipAddrs' : ['10.0.%s.1/24' % i] }
            eth1 = { 'ipAddrs' : ['192.168.%s.254/24' % i] }
            intfs = { '%s-eth0' % name : eth0,
                      '%s-eth1' % name : eth1 }

            quaggaConf = '%s/quagga%s.conf' % (CONFIG_DIR_ABILENE, i)

            router = self.addHost(name, cls=Router, quaggaConfFile=quaggaConf,
                                  zebraConfFile=zebraConf, intfDict=intfs)

            host = self.addHost('h%s' % i, cls=SdnIpHost,
                                ip='192.168.%s.1/24' % i,
                                route='192.168.%s.254' % i)

            self.addLink(router, switches['s'+name[1:]])
            self.addLink(router, host)

        # Set up the internal BGP speaker
        bgpEth0 = { 'mac':'00:00:00:00:00:01',
                    'ipAddrs' : ['10.0.%d.101/24' % (x+1) for x in range(len(switches)) ] }
        bgpEth1 = { 'ipAddrs' : ['10.10.10.1/24'] }
        bgpIntfs = { 'bgp-eth0' : bgpEth0,
                     'bgp-eth1' : bgpEth1}

        bgp = self.addHost( "bgp", cls=Router,
                             quaggaConfFile = '%s/quagga-sdn.conf' % CONFIG_DIR_ABILENE,
                             zebraConfFile = zebraConf,
                             intfDict=bgpIntfs)

        self.addLink( bgp, switches['s%d' % abilene.internal_bgp_speaker] )

        mapping = {node: 's%d' % (x+1) for x, node in enumerate(sorted(abilene.nodes))}
        print mapping

        # Wire up the switches in the topology
        capacity_dict_single_link = set([tuple(sorted(link)) for link in abilene.capacity_dict])
        for link in capacity_dict_single_link:
            self.addLink( mapping[link[0]], mapping[link[1]] )

        # Connect BGP speaker to the root namespace so it can peer with ONOS
        root = self.addHost( 'root', inNamespace=False, ip='10.10.10.2/24' )
        self.addLink( root, bgp )

class SdnIpTopo( Topo ):
    "SDN-IP tutorial topology"

    def build( self ):
        s1 = self.addSwitch('s1', dpid='00000000000000a1')
        s2 = self.addSwitch('s2', dpid='00000000000000a2')
        s3 = self.addSwitch('s3', dpid='00000000000000a3')
        s4 = self.addSwitch('s4', dpid='00000000000000a4')
        s5 = self.addSwitch('s5', dpid='00000000000000a5')
        s6 = self.addSwitch('s6', dpid='00000000000000a6')

        zebraConf = '%s/zebra.conf' % CONFIG_DIR

        # Switches we want to attach our routers to, in the correct order
        attachmentSwitches = [s1, s2, s5, s6]

        for i in range(1, 4+1):
            name = 'r%s' % i

            eth0 = { 'mac' : '00:00:00:00:0%s:01' % i,
                     'ipAddrs' : ['10.0.%s.1/24' % i] }
            eth1 = { 'ipAddrs' : ['192.168.%s.254/24' % i] }
            intfs = { '%s-eth0' % name : eth0,
                      '%s-eth1' % name : eth1 }

            quaggaConf = '%s/quagga%s.conf' % (CONFIG_DIR, i)

            router = self.addHost(name, cls=Router, quaggaConfFile=quaggaConf,
                                  zebraConfFile=zebraConf, intfDict=intfs)

            host = self.addHost('h%s' % i, cls=SdnIpHost,
                                ip='192.168.%s.1/24' % i,
                                route='192.168.%s.254' % i)

            self.addLink(router, attachmentSwitches[i-1])
            self.addLink(router, host)

        # Set up the internal BGP speaker
        bgpEth0 = { 'mac':'00:00:00:00:00:01',
                    'ipAddrs' : ['10.0.1.101/24',
                                 '10.0.2.101/24',
                                 '10.0.3.101/24',
                                 '10.0.4.101/24',] }
        bgpEth1 = { 'ipAddrs' : ['10.10.10.1/24'] }
        bgpIntfs = { 'bgp-eth0' : bgpEth0,
                     'bgp-eth1' : bgpEth1 }

        bgp = self.addHost( "bgp", cls=Router,
                             quaggaConfFile = '%s/quagga-sdn.conf' % CONFIG_DIR,
                             zebraConfFile = zebraConf,
                             intfDict=bgpIntfs )

        self.addLink( bgp, s3 )

        # Connect BGP speaker to the root namespace so it can peer with ONOS
        root = self.addHost( 'root', inNamespace=False, ip='10.10.10.2/24' )
        self.addLink( root, bgp )


        # Wire up the switches in the topology
        self.addLink( s1, s2 )
        self.addLink( s1, s3 )
        self.addLink( s2, s4 )
        self.addLink( s3, s4 )
        self.addLink( s3, s5 )
        self.addLink( s4, s6 )
        self.addLink( s5, s6 )

topos = { 'sdnip' : SdnIpTopo, 'abilene' : AbileneTopo }

if __name__ == '__main__':
    #setLogLevel('debug')

    if 'ONOS_ROOT' not in os.environ:
        print 'You must run "sudo -E python %s" to preserve environment variables!' % __file__
        exit()

    SHOW_IPERF_OUTPUT = False
    RUN_INTO_XTERM = True
    XTERM_GEOMETRY = '-geometry 80x20+100+100'
    TRAFFIC_GEN_TOOL = 'IPERF2'
    assert TRAFFIC_GEN_TOOL in ['IPERF2', 'IPERF3']

    AUTO_TRAFFIC_GENERATION = True

    if not AUTO_TRAFFIC_GENERATION:
        USE_SDNIP_TOPO = True

    '''
    iperf3 has TCP bandwith configurable but does not allow concurrent clients (sometimes it hangs and results busy)
    iperf2 has only UDP bandwith configurable but does allow concurrent clients (even if we connect to it sequentially)

    [Instructions for ONOS Build 2017 demo]

    Set these parameters in ~/robust-routing/onos/config.py
        PORT_STATS_POLLING_INTERVAL = 5
        POLLING_INTERVAL = 5
        POLLING_INTERVAL = 10
        Tstop = 10*30
        LINK_CAPACITY = 1e8
        startOnFirstNonZeroSample = True

        MIN_LEN = 10
        K = 3
        EXACTLY_K = True
        ITERATIONS = 5
        UNSPLITTABLE = True
        OLD_RR_POLICY = 2
        OBJ_FX = 'min_avg_MLU'
        INITIALIZATION = 'sequential'
        CIRCULAR_CLUSTERS = False
        AUTO_CACHING = False
        ir = IR_min_avg_MLU
        rr = RR_min_avg_MLU
        delta_def = 'MLU'
        sp = SP.min_sum_delta
        flp = FLP.min_sum_delta
        obj_fx_RTA = SP.sum_obj_fx
        obj_fx_RA = FLP.sum_obj_fx
        USE_SDNIP_TOPO = True
        MAX_NUM_OF_TM = 288
        max_TM_value = 1e8
        min_TM_value = 2e6

    Run ~/robust-routing/onos/TMtoIperf.py on the Gurobi machine

    In a terminal run:
    sudo service quagga restart; sudo mn -c
    cd ~/onos
    tools/build/onos-buck build onos --show-output; tools/build/onos-buck run onos-local -- clean debug

    Once ONOS is ready, in another terminal run:
    cd ~/onos/tools/tutorials/sdnip
    sudo -E python mn_topo_script.py

    Once "Ready to receive the configuration on TCP port 12346!" appears, run ~/robust-routing/onos/main.py on the Gurobi machine

    Once "Ready! Send the magic UDP packet..." appears press ENTER on the Gurobi machine
    '''

    if AUTO_TRAFFIC_GENERATION:
        print 'Ready to receive the configuration on TCP port 12346!'
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('',12346))
        except socket.error as msg:
            print 'Bind failed. Error Code : ' + str(msg[0]) + ' Message ' + msg[1]
            exit()
        s.listen(1)
        conn, addr = s.accept()
        rxdata = ''
        while True:
            data = conn.recv(1024)
            rxdata += data
            if not data:
                break
        pickled_config = pickle.loads(rxdata)
        TM_per_demand = pickled_config['TM_per_demand']
        USE_SDNIP_TOPO = pickled_config['USE_SDNIP_TOPO']
        POLLING_INTERVAL = pickled_config['POLLING_INTERVAL']
        V = pickled_config['V']
        conn.close()
        s.close()
        print 'Configuration received! Starting mn network...'

    topo = SdnIpTopo() if USE_SDNIP_TOPO else AbileneTopo()

    net = Mininet(topo=topo, controller=RemoteController)

    net.start()

    if AUTO_TRAFFIC_GENERATION:
        print 'Waiting 20 seconds...'
        time.sleep(5)
        print 'Waiting 15 seconds...'
        time.sleep(5)
        print 'Waiting 10 seconds...'
        time.sleep(5)
        print 'Waiting 5 seconds...'
        time.sleep(5)
        print 'Executing onos-netcfg...'
        os.system("$ONOS_ROOT/tools/package/runtime/bin/onos-netcfg localhost ./%s/network-cfg.json" % (CONFIG_DIR if USE_SDNIP_TOPO else CONFIG_DIR_ABILENE))

        print 'Opening iperf server instances...'
        # run multiple iperf3 server instances on each host, one for any other host on port is 5000 + host number
        hostList = filter(lambda host: 'h' in host.name, net.hosts)
        if TRAFFIC_GEN_TOOL == 'IPERF3':
            for dstHost in hostList:
                for srcHost in filter(lambda host: host != dstHost, hostList):
                    if SHOW_IPERF_OUTPUT:
                        cmd = "iperf3 -D -s -p %d > %s-from-%s.log 2>&1" % (5000 + int(srcHost.name[1:]), dstHost.name, srcHost.name)
                    else:
                        cmd = "iperf3 -D -s -p %d" % (5000 + int(srcHost.name[1:]))
                    dstHost.cmd(cmd)
        else:
            for srcHost in hostList:
                if SHOW_IPERF_OUTPUT:
                    cmd = "iperf -u -D -s -p %d > %s.log 2>&1" % (5000 + int(srcHost.name[1:]), srcHost.name)
                else:
                    cmd = "iperf -u -D -s -p %d" % (5000 + int(srcHost.name[1:]))
                srcHost.cmd(cmd)

        if V in [1, 2]:
            for dem in TM_per_demand:
                TM_per_demand[dem].extend(TM_per_demand[dem])

        def getHostFromIP(ip):
            return filter(lambda host: ip in host.params['ip'], net.hosts)[0]

        # create the list of iperf3 commands to be executed by each host
        start_event = threading.Event()
        for demand in TM_per_demand:
            cmd_list = []
            srcHost = getHostFromIP(demand[0] + '/24')
            dstHost = getHostFromIP(demand[1] + '/24')
            if TRAFFIC_GEN_TOOL == 'IPERF3':
                port = 5000 + int(srcHost.name[1:])
            else:
                port = 5000 + int(dstHost.name[1:])
            for bw_index, bw in enumerate(TM_per_demand[demand]):
                if TRAFFIC_GEN_TOOL == 'IPERF3':
                    cmd_list.append('iperf3 -c %s -b %dM -p %d -t %d' % (demand[1] , bw, port, POLLING_INTERVAL if bw_index != len(TM_per_demnd[demand])-1 else 3*POLLING_INTERVAL))
                else:
                    cmd_list.append('iperf -u -c %s -b %dM -p %d -t %d' % (demand[1] , bw, port, POLLING_INTERVAL if bw_index != len(TM_per_demand[demand])-1 else 3*POLLING_INTERVAL))
            ExecuteCommands(srcHost, cmd_list, start_event).start()

        # Parse SDN-IP configuration files to estimate the number of expected intents (read via ONOS REST API),
        # so that it can automatically wait for the propagation of all the BGP prefixes before starting the traffic!
        SDNIP_CONF_DIR = '%s/tools/tutorials/sdnip/%s/' % (os.popen("echo $ONOS_ROOT").read().strip(), CONFIG_DIR if USE_SDNIP_TOPO else CONFIG_DIR_ABILENE)
        # Parse the number of peering interfaces from network-cfg.json
        with open('%snetwork-cfg.json' % SDNIP_CONF_DIR) as data_file:
            data = json.load(data_file)
        peering_if = len(data['apps']['org.onosproject.router']['bgp']['bgpSpeakers'][0]['peers'])
        # Parse the number of prefixes to be announced from quagga files
        prefixes_per_peer = []
        for f in glob.glob('%squagga*.conf' % SDNIP_CONF_DIR):
            prefixes = int(os.popen("cat %s | grep network | wc -l" % f).read()) - int(os.popen("cat %s | grep \"\!network\" | wc -l" % f).read())
            if prefixes > 0:
                prefixes_per_peer.append(prefixes)
        flows = 0
        for idx1 in range(len(prefixes_per_peer)):
            for idx2 in filter(lambda x: x != idx1, range(len(prefixes_per_peer))):
                for _ in range(prefixes_per_peer[idx1]):
                    for _ in range(prefixes_per_peer[idx2]):
                     flows += 1
        intents = 0
        while intents < peering_if*2*3 + flows:
            intents = len(json_GET_req('http://localhost:8181/onos/v1/intents')['intents'])
            print 'Waiting for BGP announcements (%d more intents expected)...' % ((peering_if*2*3 + flows) - intents)
            time.sleep(1)
        # Wait for a magic packet (any UDP pkt rx on port 12345) to generate the traffic
        print 'Ready! Send the magic UDP packet on port 12345 to generate traffic from TMs'
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(('',12345))
        s.recvfrom(1024)
        s.close()

        start_event.set()

    CLI(net)

    net.stop()

    if AUTO_TRAFFIC_GENERATION:
        if SHOW_IPERF_OUTPUT:
            if TRAFFIC_GEN_TOOL == 'IPERF3':
                for dstHost in hostList:
                    for srcHost in filter(lambda host: host != dstHost, hostList):
                        os.system('echo; echo iperf %s-from-%s.log; cat %s-from-%s.log; rm %s-from-%s.log' % (dstHost.name, srcHost.name, dstHost.name, srcHost.name, dstHost.name, srcHost.name))
            else:
                for srcHost in hostList:
                    os.system('echo; echo iperf %s.log; cat %s.log; rm %s.log' % (srcHost.name, srcHost.name, srcHost.name))
    if RUN_INTO_XTERM:
        os.system('kill -9 `pidof xterm`')
    else:
        os.system('kill -9 `pidof python`')
