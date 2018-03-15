import os

capacity_dict = {
    ('ATLA', 'HSTN'): 10e9,
    ('ATLA', 'IPLS'): 10e9,
    ('ATLA', 'WASH'): 10e9,
    ('CHIN', 'IPLS'): 10e9,
    ('CHIN', 'NYCM'): 10e9,
    ('DNVR', 'KSCY'): 10e9,
    ('DNVR', 'SNVA'): 10e9,
    ('DNVR', 'STTL'): 10e9,
    ('HSTN', 'ATLA'): 10e9,
    ('HSTN', 'KSCY'): 10e9,
    ('HSTN', 'LOSA'): 10e9,
    ('IPLS', 'ATLA'): 10e9,
    ('IPLS', 'CHIN'): 10e9,
    ('IPLS', 'KSCY'): 10e9,
    ('KSCY', 'DNVR'): 10e9,
    ('KSCY', 'HSTN'): 10e9,
    ('KSCY', 'IPLS'): 10e9,
    ('LOSA', 'HSTN'): 10e9,
    ('LOSA', 'SNVA'): 10e9,
    ('NYCM', 'CHIN'): 10e9,
    ('NYCM', 'WASH'): 10e9,
    ('SNVA', 'DNVR'): 10e9,
    ('SNVA', 'LOSA'): 10e9,
    ('SNVA', 'STTL'): 10e9,
    ('STTL', 'DNVR'): 10e9,
    ('STTL', 'SNVA'): 10e9,
    ('WASH', 'ATLA'): 10e9,
    ('WASH', 'NYCM'): 10e9
}

nodes = set()
for link in capacity_dict:
    nodes.add(link[0])
    nodes.add(link[1])
nodes = sorted(list(nodes))

internal_bgp_speaker = 3

def create_conf_files():
    if not os.path.exists('configs-abilene'):
        os.makedirs('configs-abilene')
    else:
        os.system('rm configs-abilene/*')
    for x, node in enumerate(nodes):
        print 'Generating quagga%d.conf' % (x+1)
        s = "! BGP configuration for r%d" % (x+1)
        s += "\n" + "!"
        s += "\n" + "hostname r%d" % (x+1)
        s += "\n" + "password sdnip"
        s += "\n" + "!"
        s += "\n" + "router bgp %d" % (65000+x+1)
        s += "\n" + "  bgp router-id 10.0.%d.1" % (x+1)
        s += "\n" + "  timers bgp 3 9"
        s += "\n" + "  neighbor 10.0.%d.101 remote-as 65000" % (x+1)
        s += "\n" + "  neighbor 10.0.%d.101 ebgp-multihop" % (x+1)
        s += "\n" + "  neighbor 10.0.%d.101 timers connect 5" % (x+1)
        s += "\n" + "  neighbor 10.0.%d.101 advertisement-interval 5" % (x+1)
        s += "\n" + "  network 192.168.%d.0/24" % (x+1)
        s += "\n" + "!"
        s += "\n" + "log stdout\n"
        with open('./configs-abilene/quagga%d.conf' % (x+1), 'w') as f:
            f.write(s)

    print 'Generating quagga-sdn-conf'
    s = "!"
    s += "\n" + "hostname bgp"
    s += "\n" + "password sdnip"
    s += "\n" + "!"
    s += "\n" + "!"
    s += "\n" + "router bgp 65000"
    s += "\n" + "  bgp router-id 10.10.10.1"
    s += "\n" + "  timers bgp 3 9"
    for x, node in enumerate(nodes):
        s += "\n" + "  !"
        s += "\n" + "  neighbor 10.0.%d.1 remote-as %d" % (x+1, 65000+x+1)
        s += "\n" + "  neighbor 10.0.%d.1 ebgp-multihop" % (x+1)
        s += "\n" + "  neighbor 10.0.%d.1 timers connect 5" % (x+1)
        s += "\n" + "  neighbor 10.0.%d.1 advertisement-interval 5" % (x+1)
    s += "\n" + "  ! ONOS"
    s += "\n" + "  neighbor 10.10.10.2 remote-as 65000"
    s += "\n" + "  neighbor 10.10.10.2 port 2000"
    s += "\n" + "  neighbor 10.10.10.2 timers connect 5"
    s += "\n" + "!"
    s += "\n" + "log stdout\n"
    with open('./configs-abilene/quagga-sdn.conf', 'w') as f:
        f.write(s)

    print 'Generating zebra.conf'
    s = "! Configuration for zebra (NB: it is the same for all routers)"
    s += "\n!"
    s += "\nhostname zebra"
    s += "\npassword sdnip"
    s += "\nlog stdout\n"
    with open('./configs-abilene/zebra.conf', 'w') as f:
        f.write(s)

    print 'Generating gui.json'
    s = '{'
    s += '\n"hosts" : ['
    for x, node in enumerate(nodes):
        s += '\n    {"mac": "00:00:00:00:%0.2X:01", "vlan": -1, "location": "of:00000000000000%0.2x/1", "ip": "10.0.%d.1","annotations": { "type": "router" } },' % (x+1, 0xa0+x+1, x+1)
    s += '\n    {"mac": "00:00:00:00:00:01", "vlan": -1, "location": "of:00000000000000%0.2x/2", "ip": "' % (internal_bgp_speaker + 0xa0)
    for x, node in enumerate(nodes):
        s += '10.0.%d.101' % (x+1)
        if x != len(nodes) - 1:
            s += ', '
    s += '", "annotations": { "type": "bgpSpeaker" } }'
    s += '\n  ]'
    s += '\n}'
    with open('./configs-abilene/gui.json', 'w') as f:
        f.write(s)

    print 'Generating network-cfg.json'
    s = '{'
    s += '\n  "ports" : {'
    for x, node in enumerate(nodes):
        s += '\n      "of:00000000000000%0.2x/1" : {' % (0xa0+x+1)
        s += '\n      "interfaces" : ['
        s += '\n          {'
        s += '\n              "name" : "sw%d-1",' % (x+1)
        s += '\n              "ips"  : [ "10.0.%d.101/24" ],' % (x+1)
        s += '\n              "mac"  : "00:00:00:00:00:01"'
        s += '\n          }'
        s += '\n      ]'
        s += '\n    }'
        if x != len(nodes) - 1:
            s += ','
    s += '\n  },'
    s += '\n  "apps" : {'
    s += '\n      "org.onosproject.router" : {'
    s += '\n        "bgp" : {'
    s += '\n           "bgpSpeakers" : ['
    s += '\n               {'
    s += '\n                   "name" : "speaker1",'
    s += '\n                   "connectPoint" : "of:00000000000000%0.2x/2",' % (internal_bgp_speaker + 0xa0)
    s += '\n                   "peers" : ['
    for x, node in enumerate(nodes):
        s += '\n                       "10.0.%d.1"' % (x+1)
        if x != len(nodes) - 1:
            s += ','
    s += '\n                   ]'
    s += '\n               }'
    s += '\n           ]'
    s += '\n        }'
    s += '\n      },'
    s += '\n      "org.onosproject.provider.of.flow.impl.OpenFlowRuleProvider" : {'
    s += '\n           "flowPollFrequency" : 5'
    s += '\n      }'
    s += '\n   }'
    s += '\n}'

    with open('./configs-abilene/network-cfg.json', 'w') as f:
        f.write(s)

if __name__ == "__main__":
    create_conf_files()
