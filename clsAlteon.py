
import codecs
import tarfile
import re
import shlex
from collections.abc import Mapping, Sequence
from datetime import datetime
from itertools import chain

class colors:
    RED = 'FFC7CE'#00FF0000'
    YELLOW = 'FFEB9C'#'00FFFF00'

#loads a file to a string, nothing else
#todo:
##Populate variables with tuple of interfaces, groups, real servers, virtual services, etc
##Parse config string for common errors
##Maybe Later: connect to appliance and parse health checks
class clsAlteonConfig:
    def __init__(self,rawTSDmp):
        try:
            #CLI Command \/cfg\/dump:
            rawConfig = re.search(r'CLI Command \/cfg\/dump:\n=+\n([\d\D]*?)(?=\n\n===)', rawTSDmp,re.MULTILINE).group(1)
        except:
            rawConfig = ""
            
        self.rawConfig = rawConfig
        self.configElements = self._parse_config(self.rawConfig)

    def _parse_config(self, text: str) -> dict:
        # Local constants
        HEADER_PREFIXES = ("/c/", "/cfg/", "/i/", "/info/", "/o/", "/oper/", "/sta/")
        # Terminal capture modes:
        #   'text'     -> capture until a BLANK LINE
        #   'noprompt' -> capture until a line that's exactly '.'
        TEXT_TERMINALS_MODE = {"text": "until_blank_line", "noprompt": "until_dot"}

        root = {}
        self.configElements = root
        cur_node = None

        # Multi-line capture state
        capture_mode = None          # None | "until_blank_line" | "until_dot"
        text_target_node = None
        text_target_key = None
        text_buf = []

        def is_header(s: str) -> bool:
            return any(s.startswith(p) for p in HEADER_PREFIXES)

        def ensure_path(parts):
            node = root
            for p in parts:
                node = node.setdefault(p, {})
            return node

        def flush_text():
            nonlocal text_target_node, text_target_key, text_buf, capture_mode
            if text_target_node is not None and text_target_key is not None:
                text_target_node[text_target_key] = "".join(l.rstrip("\r") + "\n" for l in text_buf)
            text_target_node = None
            text_target_key = None
            text_buf = []
            capture_mode = None

        for raw in text.splitlines():
            line = raw.rstrip("\r")
            stripped = line.strip()

            # Ignore comment lines anywhere
            if stripped.startswith("/*"):
                continue

            # ----- capture modes -----
            if capture_mode is not None:
                if capture_mode == "until_dot":
                    if stripped == ".":
                        flush_text()
                        continue
                    text_buf.append(line)
                    continue
                elif capture_mode == "until_blank_line":
                    if stripped == "":
                        flush_text()
                        continue
                    text_buf.append(line)
                    continue

            # ----- headers -----
            if is_header(line):
                flush_text()

                # Split "path" and optional "tail" (handles spaces OR tabs)
                m = re.match(r"^(\S+)(?:\s+(.*))?$", line)
                path_part = m.group(1)
                tail = (m.group(2) or "").strip()

                # Build nested dicts for slash path
                path_parts = [p for p in path_part.split("/") if p]
                cur_node = ensure_path(path_parts)

                if tail:
                    # Tokenize respecting quotes, then split each token on '/'
                    toks = shlex.split(tail)
                    segments = []
                    for tok in toks:
                        segments.extend([seg for seg in tok.split("/") if seg])

                    if segments:
                        last_lower = segments[-1].lower()
                        if last_lower in TEXT_TERMINALS_MODE:
                            for seg in segments[:-1]:
                                cur_node = cur_node.setdefault(seg, {})
                            text_target_node = cur_node
                            text_target_key = segments[-1]  # keep original casing
                            text_buf = []
                            capture_mode = TEXT_TERMINALS_MODE[last_lower]
                        else:
                            for seg in segments:
                                cur_node = cur_node.setdefault(seg, {})
                            capture_mode = None
                continue

            # ----- indented key/value lines -----
            if line[:1] in (" ", "\t"):
                if cur_node is None:
                    continue
                s = line.lstrip(" \t")
                if not s:
                    continue

                parts = shlex.split(s)
                if not parts:
                    continue

                # Start capture from an indented terminal (e.g., "import text")
                last_lower = parts[-1].lower()
                if last_lower in TEXT_TERMINALS_MODE and len(parts) >= 2:
                    text_target_node = cur_node
                    text_target_key = parts[0]      # e.g., 'import'
                    text_buf = []
                    capture_mode = TEXT_TERMINALS_MODE[last_lower]
                    continue

                k = parts[0]
                v_parts = parts[1:]

                # ----- special handling for 'add' -----
                if k.lower() == "add":
                    if not v_parts:
                        # plain "add" → treat as empty list starter (rare)
                        cur_node.setdefault("add", [])
                    elif len(v_parts) == 1:
                        # "add N" → list form, e.g., ['1','2']
                        existing = cur_node.get("add")
                        if not isinstance(existing, list):
                            cur_node["add"] = [] if existing is None else [existing]
                        cur_node["add"].append(v_parts[0])
                    else:
                        # "add N NAME..." → indexed form: {'add': {'N': {'NAME...': ''}}}
                        idx = v_parts[0]
                        name = " ".join(v_parts[1:])
                        if not isinstance(cur_node.get("add"), dict):
                            cur_node["add"] = {}
                        cur_node["add"].setdefault(idx, {})
                        cur_node["add"][idx][name] = ""
                    continue

                # ----- normal flat assignment -----
                cur_node[k] = " ".join(v_parts) if v_parts else ""
                continue

            # All other lines outside capture: ignore

        flush_text()
        return root
    
    def getUnusedEntries(self) -> list:
        
        def findAddElement(element, searchRange):
            for key, value in searchRange.items():
                if element in value.get('add',[]):
                    return True
            return False
        #find unused servers:
        unusedServers=[]
        for real,contents in self.configElements.get('c',{}).get('slb',{}).get('real',{}).items():
            if not findAddElement(real,self.configElements.get('c',{}).get('slb',{}).get('group',{})):
                unusedServers.append(real)
        #print(f"Unused servers: {unusedServers}")

        #Find unused groups:
        emptyGroups=[]
        unusedGroups=[]
        for group, contents in self.configElements.get('c',{}).get('slb',{}).get('group',{}).items():
            if len(contents.get('add', [])) == 0:
                #No servers - it's stale
                emptyGroups.append(group)
    
            matches = re.findall(rf'group {group}$', self.rawConfig, re.MULTILINE)
            if len(matches) < 2:
                unusedGroups.append(group)
        #print(f"Empty groups: {emptyGroups}")
        #print(f"Unused groups: {unusedGroups}")
        
        #Find unused SSL policies
        unusedSSLPolicies=[]
        for policy, contents in self.configElements.get('c',{}).get('slb',{}).get('ssl',{}).get('sslpol',{}).items():
            matches = re.findall(rf'sslpol {policy}$', self.rawConfig, re.MULTILINE)
            if len(matches) < 2:
                unusedSSLPolicies.append(policy)
        #print(f"Unused sslpol: {unusedSSLPolicies}")

        #Find unused SSL Certs
        unusedSSLCerts=[]
        for cert, contents in chain(
                                self.configElements.get('c',{}).get('slb',{}).get('ssl',{}).get('certs',{}).get('cert',{}).items(),
                                self.configElements.get('c',{}).get('slb',{}).get('ssl',{}).get('certs',{}).get('intermca',{}).items()
                                ):
            matches = re.findall(rf'cert {cert}$', self.rawConfig, re.MULTILINE)
            if len(matches) < 2:
                unusedSSLCerts.append(cert)
        #print(f"Unused SSL Certs: {unusedSSLCerts}")



        #Find unused Health Checks
        unusedHealthChecks=[]
        for hc, contents in self.configElements.get('c',{}).get('slb',{}).get('advhc',{}).get('health',{}).items():
            matches = re.findall(rf'health {hc}$', self.rawConfig, re.MULTILINE)
            if len(matches) < 2:
                unusedHealthChecks.append(hc)
        #print(f"Unused sslpol: {unusedHealthChecks}")

        #Find unused Appshape Scripts
        ##This one is more complicated since appshape scripts can be used in many places.
        #    For faster processing, first build a list of existing scripts.
        def find_key_deep(obj, target="appshape", *, case_insensitive=False):
            """
            Yield (path_list, value) for every occurrence of `target` as a dict key
            in a nested structure of dicts/lists/tuples.
            """
            match = (lambda k: k.lower() == target.lower()) if case_insensitive else (lambda k: k == target)
            stack = [([], obj)]

            while stack:
                path, cur = stack.pop()

                if isinstance(cur, Mapping):
                    for k, v in cur.items():
                        if isinstance(k, str) and match(k):
                            yield (path + [k], v)
                        stack.append((path + [k], v))

                elif isinstance(cur, Sequence) and not isinstance(cur, (str, bytes, bytearray)):
                    for i, v in enumerate(cur):
                        stack.append((path + [i], v))
		
        usedScripts = []
        for path, value in find_key_deep(self.configElements, "appshape"):
            #print(" -> ".join(map(str, path)), "=", value)
            if path != ['c', 'slb', 'appshape']:
                for index, scripts in value.get('add',{}).items():
                    for script in scripts.keys():
                        usedScripts.append(script)
        #    Now check if all our scripts are in the list of used scripts
        unusedScripts = []
        for script in self.configElements.get('c',{}).get('slb',{}).get('appshape',{}).get('script',{}).keys():
            if script not in usedScripts:
                unusedScripts.append(script)
        #print(f"Unused Appshape++ scripts: {unusedScripts}")

        outputElements = {
            "Unused Servers": unusedServers,
            "Empty Groups": emptyGroups,
            "Unused Groups": unusedGroups,
            "Unused SSL Policies": unusedSSLPolicies,
            "Unused SSL Certificates": unusedSSLCerts,
            "Unused Health Checks": unusedHealthChecks,
            "Unused Appshape++ Scripts": unusedScripts
        }
        output = {}
        output['text'] = ""
        for key, list in outputElements.items():
            if len(list) > 0:
                output['text'] += f"{key}: {', '.join(list)}\n"
                output['color'] = colors.YELLOW

        return output



#Opens a TechData.tgz. Extracts and analyzes the tsdmp file contained within.
#Todo, VX files are in different places than standalone alteon. Take this into account
class clsTechData:#Incomplete
    def __init__(self,path,file):
        self.filename=file
        self.outputCells = []
        #Open the .tgz file and place specific files into variables
        with tarfile.open(path + '/' + file,'r:gz') as tar:
            #for tarinfo in tar.getmembers():
            #    print(tarinfo.name)
            #tar.extractfile
            
            #Open alteon config files:
            #try:
            #    extractedFile = tar.extractfile("/disk/Alteon/Config/config_vx.txtt")
            #    self.vxConfig = codecs.getreader("ANSI")(extractedFile).read()
            #except:
            #    self.vxConfig=""

            #try:
            names = tar.getnames()
            print("Sample of archive contents:")
            for name in names:
                if "tsdmp" in name:
                    print("  ", name)
            if "/disk/Alteon/tsdmp" in names:
                member = tar.getmember("/disk/Alteon/tsdmp")
            elif "/disk/Alteon/techdata/vadc/1/tsdmp_vadc_1" in names:
                member = tar.getmember("/disk/Alteon/techdata/vadc/1/tsdmp_vadc_1")
            else:
                pattern = re.compile(rf"{re.escape('/disk/Alteon/techdata/vadc/')}(\d+)/tsdmp_vadc_\1")
                for name in names:
                    if pattern.fullmatch(name):
                        member = tar.getmember(name)
                        break
                else:
                    member = None

            if member:
                extractedFile = tar.extractfile(member)
                self.TSdmp = clsTSdmp(codecs.getreader("utf-8")(extractedFile, errors='ignore').read(), file)

                if extractedFile:
                    print(f"Extracted: {member.name}")
                else:
                    print(f"Failed to extract: {member.name}")
            else:
                print("Neither target file was found in the archive.")

            #except Exception as e:
            #    print("TSdmp file read error:",e)
            #    self.TSdmp=""
            
            if len(self.TSdmp.raw) > 0:
                print("TSdmp found. Analyzing")
                self.outputCells = self.TSdmp.analyze()

class clsTSdmp:
    #Receives a string containing a complete TSDMP
    def __init__(self,strTSdmp,fileName):
        self.raw=strTSdmp
        self.fileName = fileName
        self.alteonConfig = clsAlteonConfig(self.raw)

    def analyze(self):
        '''Analyzes the tsdmp file for various common issues'''

        ##Enable colored console output
        #os.system('color')

        print(f"Analyzing {self.fileName}")
        self.lastSyncTime = ''
        self.lastSaveTime = ''
        self.lastApplyTime = ''

        self.Name = {'text': self.fileName}
        self.Hostname = self.getHostname()
        self.IP = self.getmgmtIP()
        self.BaseMac = self.getBaseMac()
        self.LicenseMac = self.getLicenseMac()
        self.Model = self.getModel()
        self.SWVersion = self.getSWVersion()
        self.Date = self.getDate()
        self.vADCs = self.getvADCs()
        self.Uptime = self.getUptime()
        self.HAInfo = self.getHAInfo()
        self.ApplyFlags = self.getApplyData() or {'text':"Error retrieving flags"}
        self.SSHSessions = self.checkSSHSessions()
        self.AllocationFailures = self.checkAllocationFailures()
        self.LicenseUtilization = self.checkLicenseUtilization()
        self.SessionTableAllocation = self.checkSessionTableAllocation()
        self.PanicDumps = self.checkPanicDumps()
        self.AlarmingSyslogs = self.checkAlarmingSyslogs()
        self.AuthServers = self.checkAuthServers()
        self.ManagementACLs = self.checkManagementACLs()
        self.RealServerStates = self.checkRealServerStates()
        #checkFQDNServerStates doesn't correctly parse yet so we parse it here
        checkFQDNOut = self.checkFQDNServerStates()
        self.RealServerStates['text'] += "\n" + checkFQDNOut['text']
        print("'FQDN server state:' not checked. Must be checked manually.")
        self.VirtualServerStates = self.checkVirtualServerStates()
        #print("'IDS group state:' not checked. Must be checked manually.")
        
        self.listVirtualServers()
        
        self.Fans = self.checkFans()
        self.Temp = self.checkTemp()
        self.interfaces = self.getInterfaces()
        self.PortsEther = self.checkPortsEther()
        self.PortsIf = self.checkPortsIf()
        self.UnusedPolicy = self.alteonConfig.getUnusedEntries()
        

        
        return [ 
            self.Hostname,
            self.Name,
            self.IP,
            self.BaseMac,
            self.LicenseMac,
            self.Model,
            self.SWVersion,
            self.Date,
            self.vADCs,
            self.Uptime,
            self.HAInfo,
            self.ApplyFlags,
            self.SSHSessions,
            self.AllocationFailures,
            self.LicenseUtilization,
            self.SessionTableAllocation,
            self.PanicDumps,
            self.AlarmingSyslogs,
            self.AuthServers,
            self.ManagementACLs,
            self.RealServerStates,
            self.VirtualServerStates,
            self.Fans,
            self.Temp,
            self.interfaces,
            self.PortsEther,
            self.PortsIf,
            self.UnusedPolicy
        ]

    def getHostname(self):
        #Search config for snmp name
        output = {}
        try:
            match = re.search(r'(?<=/c/sys/ssnmp\n)([\d\D]+?)(?=\n/)',self.raw,re.MULTILINE)
            #print(match.group())
            name = re.search(r'(?:name ")([\d\D]+?)(?:")',match.group(),re.MULTILINE)
            output['text'] = name.group(1)
        except:
            output['text'] = "N/A"
            output['color'] = colors.YELLOW
        return output
    
    def getmgmtIP(self):
        #CLI Command /info/sys/mgmt:
        output = {'text': ''}
        match = re.search(r'(?<=^CLI Command /info/sys/mgmt:\n={106}\n)([\d\D]+?)(?=\n====)', self.raw, re.MULTILINE).group()
        #ip = re.search(r'(?<=^Interface information:\n )([\d\D]+?)(?=\s)',match,re.MULTILINE).group()
        #ip = re.search(r'(?<=^Interface information:\n )([^\s]+)(?:[^\n]*\n ?([^\s]+))?',match,re.MULTILINE)
        ip = re.search(r'(?<=^Interface information:\n)(?:^ +([^\s]+)[^\n]*\n?)(?:^ +([^\s]+)[^\n]*\n?)?', match, re.MULTILINE)
        output['text'] = ip.group(1)
        if ip.group(2):
            output['text'] += '\n' + ip.group(2)
        #print(output['text'])

        return output
    
    def getBaseMac(self):
        """Returns the appliance base MAC address"""
        
        output = {}

        output['text'] = re.search(r'(?<=Base MAC: )([\d\D]+?$)', self.raw, re.MULTILINE).group()
        #print(f'Base MAC: {output["text"]}')
        return output
    
    def getLicenseMac(self):
        """Returns the appliance upgrade MAC address"""

        output = {}

        match = re.search(r'(?<=License Key                :    )([\d\D]+?$)', self.raw, re.MULTILINE)
        if match != None:
            output['text'] = match.group()
        else:
            output['text'] = "HW-Same As Base Mac"

        #print(output['text'])
        #print(f'License Key: {output["text"]}')
        return output or ""

    def getModel(self):
        """Returns the appliance model name"""
        
        output = {}

        match = re.search(r'(?<=Memory profile is)(?:.+\n\n)([\d\D]+?$)', self.raw, re.MULTILINE)
        if not match:
            match = re.search(r'(?<=Hw Type )(.+?)$', self.raw, re.MULTILINE)
        
        if match:
            output['text'] = match.group(1)
        else:
            output['text'] = 'N/A'

        #print(f'Model: {output["text"]}')
        return output
    
    def getSWVersion(self):
        """Returns the OS SWVersion"""
                
        output = {'text':''}
        match = re.search(r'(?<=ADC-VX Infrastructure Software Version )([\d\D]+?)(?=, Image ID )', self.raw, re.MULTILINE)
        if match:
            #VX
            output['text'] = 'VX: ' + match.group() + '\n'
            match = re.search(r'(?<=ADC Application Software Version )([\d\D]+?)(?=, Image ID )', self.raw, re.MULTILINE)
            if match:
                output['text'] += 'ADC: ' + match.group()
            else:
                match = re.search(r'(?<=ADC Application Software Version )([\d\D]+?)(?= \(|\n)', self.raw, re.MULTILINE)
                output['text'] += 'ADC: ' + match.group()
        else:
            match = re.search(r'(?<=Software Version )([\d\D]+?)(?= Image ID )', self.raw, re.MULTILINE)
            if match:
                output['text'] = match.group()
            else:
                match = re.search(r'(?<=Software Version )([\d\D]+?)(?= \(|\n)', self.raw, re.MULTILINE)
                output['text'] = match.group()
                

            #print(f'Running Software Version: {output["text"]}')
        return output
    def getDate(self):
        """Returns the tsdmp datestamp"""
        
        output = {}

        output['text'] = re.search(r'(?<=^TIMESTAMP:  )([\d\D]+?)(?= )', self.raw, re.MULTILINE).group()
        #print(f'TSDmp datestamp: {output["text"]}')
        return output
    def getvADCs(self):
        """Returns vADC info for VX hosts"""
        output = {'text':''}

        match = re.search(r'Show vADC informaion summary from CLI Command /info/vadc:\n={57}\n([\d\D]+?)(?=^=)',self.raw, re.MULTILINE)
        if match:
            config = match.group(1)
            
            cu_match = re.search(r'Available CUs:\s+(\d+)\((\d+)\)', config)
            if cu_match:
                output['text'] += f"Available CUs: {cu_match.group(1)}/{cu_match.group(2)}"

            tp_match = re.search(r'Available Throughput:\s+([\d.]+)Gbps', config)
            if tp_match:
                output['text'] += f"\nAvailable Throughput: {tp_match.group(1)}Gbps"

            vADC_matches = re.findall(r'^\s*(\d+)\s+(\S+)\s+(\S+\(.*?\))\s+(\d+)\s+\d+\s+\d+\s+(\S+)\s+(\S+)', config, re.MULTILINE)
            if vADC_matches:
                output["text"] += f"\nvADCs:"
                for vadc_id, name, status, cus, ha_state, sp_cpu_avg in vADC_matches:
                    output['text'] += f"\n  {vadc_id}:  {name} status:{status} {cus}CUs HA_State:{ha_state}"

            return output
        else:
            return {'text':'N\A'}


    def getUptime(self):
        """Returns the tsdmp Time since last reboot"""
        output = {}

        match = re.search(r'(^Switch is up [\d\D]+?minute(?:s)?)(?= |\n)', self.raw, re.MULTILINE)
        if not match:
            match = re.search(r'(^vADC \d{1,2} is up [\d\D]+?minute(?:s)?)(?= |\n)', self.raw, re.MULTILINE)
        if not match:
            match = re.search(r'(?<=^vADC \d\d is up )([\d\D]+?minute(?:s)?)(?= |\n)', self.raw, re.MULTILINE)

        if match:
            output['text'] = match.group()
        else:
            output['text'] = 'n/a'
        #print(f'Time since last reboot: {output["text"]}')
        return output
    
    def getHAInfo(self):
        """Returns a cleaned up version of the output of /info/l3/ha"""
        output = {}
        info = re.search(r'(?:^CLI Command \/info\/l3\/ha :\n=+\n)([\d\D]+?)(?:\n\n|\n \n)', self.raw, re.MULTILINE)
        if not info:
            info = re.search(r'(?:CLI Command \/info\/l3\/ha:\n=+\n)([\d\D]+?)(?:\n\n|\n \n)', self.raw, re.MULTILINE)

        if info:
            info = info.group(1)
        info = info.replace('High Availability mode is','Mode:')
        info = info.replace(' - information:','',1)
        info = info.replace('High Availability is globally disabled.','Disabled')
        info = info.replace('\tTracked','\nTracked')
        info = info.replace('\t','  ')
         
        if info.count('State: init') > 0:
            output['color'] = colors.YELLOW
        #print('')
        #print(info)
        output['text'] = info

        match = re.search(r'(?:^/c/l3/ha/switch\s*\n\s+def )([\d\D]+?)(?:\n)', self.raw, re.MULTILINE)
        if match:
            advertisementInterfaces = match.group(1).strip().split(' ')
            allInterfaces = re.findall(r'/c/l3/if (\d+)((?:\n\s.*)*)', self.raw)
            interfaces = {}
            nonAdvertisementInterfaces = []
            for ifNum, block in allInterfaces:
                addr = re.search(r'addr ([^\s]+)', block)
                peer = re.search(r'peer ([^\s]+)', block)
                descr = re.search(r'descr "([^"]+)"', block)
                interfaces[ifNum] = {
                    'addr': addr.group(1) if addr else "",
                    'peer': peer.group(1) if peer else "",
                    'descr': descr.group(1) if descr else ""
                }
                if not ifNum in advertisementInterfaces:
                    nonAdvertisementInterfaces.append(ifNum)
            output['text'] += f'\nAdvertisement Interfaces: {", ".join(advertisementInterfaces)}'
            for interface in advertisementInterfaces:
                output['text'] += f"\n    {interface}: {interfaces[interface]['addr']}"
                if len(interfaces[interface]['descr']) > 0:
                     output['text'] += f" ({interfaces[interface]['descr']})"
            output['text'] += f'\nNon-advertising interfaces: {", ".join(nonAdvertisementInterfaces)}'
            for interface in nonAdvertisementInterfaces:
                output['text'] += f"\n    {interface}: {interfaces[interface]['addr']}"
                if len(interfaces[interface]['descr']) > 0:
                     output['text'] += f" ({interfaces[interface]['descr']})"
            if len(nonAdvertisementInterfaces) > 1:
                output['color'] = colors.YELLOW

        return output
    
    def getApplyData(self):
        """Returns a parsed version of /maint/debug/prntGlblApplyFlgs"""
        output = {}
        output['text'] = ''
                
        sysGeneral = re.search(r'(?:^CLI Command \/info\/sys\/general:\n=+\n)([\d\D]+?)(?:\n=)', self.raw, re.MULTILINE).group(1)
        self.lastApplyTime = re.search(r'(?:Last apply: )([\d\D]*?)(?:$)',sysGeneral,re.MULTILINE).group(1)
        self.lastSaveTime = re.search(r'(?:Last save: )([\d\D]*?)(?:$)',sysGeneral,re.MULTILINE).group(1)

        if len(self.lastApplyTime) > 0:
            dateApply = datetime.strptime(self.lastApplyTime,"%H:%M:%S %a %b %d, %Y")
            output['text'] += "Last Apply: " + dateApply.strftime("%Y %B %d %H:%M:%S") + '\n'
        else:
            output["text"] += "Last Apply: N\A\n"
            output['color'] = colors.YELLOW
            dateApply = 0
        if len(self.lastSaveTime) > 0:
            dateSave = datetime.strptime(self.lastSaveTime,"%H:%M:%S %a %b %d, %Y")
            output['text'] += "Last Save: " + dateSave.strftime("%Y %B %d %H:%M:%S") + '\n'
        else:
            output["text"] += "Last Save: N\A\n"
            output['color'] = colors.YELLOW
            dateSave = 0
            
        try:
            HAInfo = re.search(r'(?:^CLI Command \/info\/l3\/ha :\n=+\n)([\d\D]+?)(?:\n\n|\n \n)', self.raw, re.MULTILINE).group(1)
            lastSync = re.search(r'(?:Last sync config time: )([\d\D]+?)(?:\n)',HAInfo,re.MULTILINE).group(1)
            self.lastSyncTime = lastSync
            dateSync = datetime.strptime(self.lastSyncTime,"%H:%M:%S %a %b %d, %Y")
            output['text'] += "Last Sync: " + dateSync.strftime("%Y %B %d %H:%M:%S") + '\n'
            if dateApply > dateSync:
                output['text'] = "Sync needed!\n" + output['text']
                output['color'] = colors.YELLOW
        except:
            print("Error getting sync time")
            self.lastSyncTime = ''

        if dateApply > dateSave:
            #Apply is newer than last save
            output['text'] += '\nSave needed\n'
            output['color'] = colors.RED
        # else:
        #     print(dateApply,"<",dateSave)
        
        commandOutput = re.search(r'(?:^CLI Command \/maint\/debug\/prntGlblApplyFlgs:\n=+\n)([\d\D]+?)(?:\n\n|\n \n)', self.raw, re.MULTILINE).group(1)
        flags = re.search(r' 1\)[\d\D]*',commandOutput,re.MULTILINE).group()
        #if re.search(r'slb_cfg_apply_needed\s+1$',flags,re.MULTILINE):
        #    output['text'] += "flag:Apply Needed\n"
        #    output["color"] = colors.RED
        changesneeded = re.search(r'Note: There are configuration changes pending.  Use "diff"', self.raw, re.MULTILINE)
        if changesneeded:
            output['text'] = "flag:Apply Needed\n" + output['text']
            output["color"] = colors.RED

        syncState = re.search(r'(?:rs_cfg_sync_status\s+)(\d)(?:$)',flags,re.MULTILINE)
        output['text'] += 'Sync State: ' + syncState.group(1)

        #print(output)

        return output

    def checkSSHSessions(self):
        """Checks the tsdmp for long SSH sessions"""
        output = {}
        #Regex explanation: 
        # (Lookbehind for '/who: <Newline> <84 = in a row> <newline>)(Match any character including newlines, repeat, nongreedy)(Lookahead for <newline><newline>)
        #print("Checking SSH Sessions")
        try:
            slashWho = re.search(r'(?<=\/who: \n={84}.\n)([\d\D]*?)(?=\n\n)', self.raw).group()
        except:
            slashWho = []

        #Display to console
        if len(slashWho) > 0:
            #Todo - perform pruning of self.slashWho and only return data for >1 hour entries. Output needs to be reformatted into a raw array
            output['text'] = f'{len(slashWho.splitlines()) - 3} entries found{":" if len(slashWho) > 0 else "."}\n{slashWho.replace("	"," ")}'
            #print('/who: Possible long SSH entries. Long (multiple hour) SSH entries can be indicative of an issue:')
            for line in output:
                print('    ', line)
        else:
            #print('/who: No SSH sessions found')
            output['text'] = 'None'
        #print('')

        return output
    
    def checkAllocationFailures(self):
        """Outputs lines from the tsdmp that contain PIP allocation failures.
        PIP failures could be a port exhaustion issue.
        Output contains a list of failures in the form of:
        [[<PIP>, <Current Free>, <Current Used>, <Allocation Failures>],[...]]"""

        output = {'text' : ''}
        
        #Perform a regex search for the following two lines. This section may occur in the tsdmp more than once.
        #                                         Current  Current pport allocation
        #Proxy IP address                            free     used  failure
        #--------------------------------------- -------- -------- ----------
        #Regex explanation:
        # (lookahead for searchString)(Match specified characters, repeat, nongreedy)(Lookahead for <newline><newline>)
        PIPSearchString="Proxy IP address                            free     used  failure\n" + \
        "--------------------------------------- -------- -------- ----------\n"
        matches = re.findall(r'(?<=' + re.escape(PIPSearchString) + r')([\w\. \/\n]*?)(?=\n^-)', self.raw,re.MULTILINE)

        #matches now contains an array of matches. Join them with a newline character between each
        PIPs = "\n".join(matches).splitlines()
        
        #Perform a regex search for the following two lines. This section may occur in the tsdmp more than once.
        #Proxy IP subnets                       
        #---------------------------------------
        #Regex explanation:
        # (lookahead for searchString)(Match specified characters, repeat, nongreedy)(Lookahead for <newline><newline>)
        searchString=("Proxy IP subnets                       \n" +
        "---------------------------------------\n")
        matches = re.findall(r'(?<=' + re.escape(searchString) + r')([\w\. \/\n]*?)(?=\n-)', self.raw,re.MULTILINE)
        PIPs += "\n".join(matches).splitlines()

        #Temp: Printing all found pips for testing purposes. Remove in final.
        #print(f'{len(PIPs)} pips found:')
        #print(PIPSearchString)
        #print("\n".join(PIPs))

        failurePIPs = []
        for PIP in PIPs:
            #Break PIP entry into an array. [PIP, CurrentFree, Used, Failures]
            PIPdata = PIP.split()
            if len(PIPdata) >=3:
                #if there are a nonzero number of failures, include the PIP array in the failurePIPs array.
                if PIPdata[3] != '0':
                    failurePIPs.append(PIPdata)

        output['text'] = f'{len(PIPs)} pips checked. {len(failurePIPs)} failed.'
        if len(failurePIPs) > 0:
            #print("/stats/slb/dump: PIP failures detected:\n" + \
            #    "     [<PIP>, <free>, <used>, <failures>]")
            
            for PIP in failurePIPs:
            #    print('    ', PIP)
                output['text'] += f'{PIP[0]}: {PIP[3]} failures\n'
            output['color'] = colors.RED
        # else:
        #     if len(PIPs) > 0:
        #         print(f"/stats/slb/dump: {len(PIPs)} PIPs found. No PIP failures detected.")
        #     else:
        #         print("/stats/slb/dump: No PIPs detected")
        # print('')
        for pip in failurePIPs:
            output['text'] = f'{pip[0]}: {pip[3]} failures\n'

        return output
    
    def checkLicenseUtilization(self):
        """Check license capacity utilization. Threshold for reporting is > 60% of licensed maximum.
        Outputs a list in the form of [[Feature,Capacity,PeakUsage(in MB),CurrentUsage(in MB)],[...]]"""
        #Source - /info/swkey

        output = {'text' : ''}
        overThresholdLicenses = []

        #Find (Section Start)(Match letters and mumbers)(Section end)
        matches = re.search(r'(?<=Capacity Utilization\n====================\n)([\d\D]*?)(?=\n\n)', self.raw)
        if matches:
            matches = matches.group()
        else:
            output['text'] = 'Capacity N/A'
            return output
        features = matches.splitlines()

        #the first 2 lines in features are headings. Loop through the rest
        for feature in features[2:]:
            #Removes spaces between digit and unit symbol. ex: '4 Gbps' becomes '4Gbps'
            line = re.sub(r'(?<=\d) (?=\D)', "", feature)
            line = re.sub(r'Ingress Throughput','IngressThroughput', line)
            line = line.split()
            # print("#####")
            # print(line)

            #Compares Licensed limit with PeakObserved. Returns True if Peak is > (Max * 60%)
            if self.__isOverThreshold(line[1], line[2]):
                 #Insert space between number and units label. Ex: '6Gbps' becomes '6 Gbps'
                for i in range(1,4):
                    line[i] = re.sub(r'(?<=\d)([a-zA-Z])', r' \1', line[i])
                overThresholdLicenses.append(line)
                output['color'] = colors.RED

        #Display to console
        if len(overThresholdLicenses) > 0:
            # print("Observed traffic exceeds 60% of licensed maximum for the following licenses:")
            # print("     [Feature, Capacity, PeakUsage, CurrentUsage]")
            # for line in overThresholdLicenses:
            #     print('    ', line)
            output['color'] = colors.YELLOW
        # else:
        #     print("License check passed. No traffic exceeded 60% of licensed limit.")
        # print('')
        #print(overThresholdLicenses)
        
        output['text'] =  "\n".join([f.strip() for f in features[2:]])
        return output

    def __isOverThreshold(self,limit,peakObserved):
        """Compares limit to peakObserved. Returns true if peakObserved is > 60% of limit. False otherwise"""
        
        #Unlimited licenses will never be over limit. 
        if limit == "Unlimited":
            return False
        
        #Splits number from unit symbol
        limitSplit = re.split(r'(?<=[\d])(?=\D*$)',limit)
        peakSplit = re.split(r'(?<=[\d])(?=\D*$)',peakObserved)

        #Convert number to Mbps
        limitSplit[0] = float(limitSplit[0])
        if limitSplit[1].upper() == 'TBPS':
            limitSplit[0] *= (1024 * 1024)
        elif limitSplit[1].upper() == 'GBPS':
            limitSplit[0] *= 1024
        elif limitSplit[1].upper() == 'KBPS':
            limitSplit[0] /= 1024
        elif limitSplit[1].upper() == 'BPS':
            limitSplit[0] /= (1024 * 1024)

        #Convert number to Mbps
        peakSplit[0] = float(peakSplit[0])
        if peakSplit[1].upper() == 'TBPS':
            peakSplit[0] *= (1024 * 1024)
        elif peakSplit[1].upper() == 'GBPS':
            peakSplit[0] *= 1024
        elif peakSplit[1].upper() == 'KBPS':
            peakSplit[0] /= 1024
        elif peakSplit[1].upper() == 'BPS':
            peakSplit[0] /= (1024 * 1024)

        #Compare
        if peakSplit[0] > (limitSplit[0] * .6):
            return True
        else:
            return False
        
    def checkSessionTableAllocation(self):
        """Checks /stats/slb/peakinfo to verify the session table has been allocated 50% of memory.
        Returns session table value. Ex:50 for 50%"""
        
        output = {'text' : ''}

        #Find (Section Start)(Match letters and mumbers)(Section end)
        matches = re.search(r'(?<=Show peak data information from CLI Command /stats/slb/peakinfo:\n)([\d\D]*?)(?=\n\n)', self.raw).group()
        lines = matches.splitlines()
        if len(lines) <= 1:
            output['text'] = 'SessionTable N/A'
            return output
        #Lines now contains [==========, HW type, Mem Capacity, Sess Table Setting, Data Table Setting, Peak Sessions, Peak AX Sessions, Peak Data Table]
        
        #Grab the % value from line3 (session table setting)
        value = re.search(r'(?<= )(\d*?)(?=%$)', lines[3]).group()
        
        #Display to console and return
        if value != '50':
            # print('/stats/slb/peakinfo: It is recommended that the session table value is set to 50%. The current value is:')
            # print('    ', lines[3])
            output['color'] = colors.YELLOW
        # else:
        #     print('/stats/slb/peakinfo: session table value is correct (50%)')
        # print('')

        output['text'] = value + ' %'
        return output
    
    def checkPanicDumps(self):
        """Checks '/maint/lsdmp and /maint/coredump/list for panic dumps.
        """
        
        output = {}
        out = []

        matches = re.search(r'(?<=Show the panic dump available in flash memory from CLI Command /maint/lsdmp:\n)([\d\D]*?)(?=\n\n\n)',self.raw).group()
        lines = matches.splitlines()
        
        #the first line contains '=======' the rest are relevant
        for line in lines[1:]:
            if not line.strip().startswith("No"):
                out.append(line.strip())

        match = re.search(r'(?<=Show the list of available core dump files from CLI command /maint/coredump/list:\n)([\d\D]*?)(?=\n\n\n)', self.raw)
        if match:
            matches = match.group()
            lines = matches.splitlines()
        else:
            lines = ''
        
        #the first line contains '=======' the rest are relevant
        for line in lines[2:]:
            if not line.strip().startswith("No"):
                out.append(line.strip())
        
        #Display to console
        # if len(out) > 0:
        #     print("/maint/lsdmp and /maint/coredump/list: The following panic dumps were found:")
        #     for line in out:
        #         print('    ',line)
        # else:
        #     print("/maint/lsdmp and /maint/coredump/list: No panic dumps were found.")
        # print('')

        output['text'] = '\n'.join(out)
        return output

    def checkAlarmingSyslogs(self):
        """Checks /info/sys/log: - latest 200 syslog entries for ALERT, Critical, or WARNING entries
        returns a list of the entries."""

        matches = re.search(r'(?<=CLI Command /info/sys/log:\n)([\d\D]*?)(?=\n\n\=)', self.raw).group()
        allLogs = matches.splitlines()

        logDict = {}
        output = {'text' : ''}

        #Go through all logs starting at log 4. The first 4 lines are part of the header/whitespace
        for log in allLogs[4:]:
            if log.count("ALERT") > 0 or log.count("CRITICAL") > 0 or log.count("WARNING") > 0:
                #Strip the time/date stamp from the log so we can count how many times this log repeats
                #stamplessLog = re.search(r'(ALERT|CRITICAL|WARNING)\s+.*$', log).group() 
                stamplessLog = re.search(r'(?<=:\d\d )+.*$', log).group()
                #See if there is a key in the logDict dictionary for the stripped log
                if not stamplessLog in logDict:
                    #No key found for strippedLog. Create one and store a counter and the most recent full log line as it's value.
                    logDict[stamplessLog] = [1, log.strip()]
                else:
                    #The key already exists. Increment the counter for this entry by 1.
                    logDict[stamplessLog] = [logDict[stamplessLog][0] + 1, logDict[stamplessLog][1]]

        if len(logDict) > 0:
            #logDict = sorted(logDict.items(),key=lambda x:x[1])
            logDict = dict(sorted(logDict.items(), key=lambda x:x[1], reverse=True))
            
            #print("/info/sys/log: Latest 200 syslog entries contain entries that could require attention:")
            for log in logDict:
                #print('    ', f'{logDict[log][1]} - Repeated {logDict[log][0]} times')
                #With timestamp: output['text'] += f'{logDict[log][0]}: {logDict[log][1]}'
                output['text'] += f'{logDict[log][0]}: {logDict[log][1]}\n'
                #without timestamp: output['text'] += f'{logDict[log][0]}: {log}\n'
        # else:
        #     print("/info/sys/log: Latest 200 syslog entries searched. No ALERT, CRITICAL, or WARNING messages found.")
        # print('')

        #Return a list instead of a dictionary.
        #return list(logDict.items())
        return output
    
    def checkAuthServers(self):
        """Checks /info/sys/capacity:
        Returns text with auth server counts"""

        output = {'text' : ''}

        matches = re.search(r'(?<=CLI Command /info/sys/capacity:\n)([\d\D]*?)(?=\n\n\=)', self.raw).group()
        allCapacities = matches.splitlines()
        
        #Count how many radius and tacacs+ servers are configured
        serverCount = 0
        for capacity in allCapacities:
            if capacity.startswith('RADIUS servers') or capacity.startswith('TACACS+ servers'):
                capacitySplit = capacity.split()
                serverCount += int(capacitySplit[3])
                output['text'] += f"{capacitySplit[0]} {capacitySplit[1]}: {capacitySplit[3]}\n"
        if serverCount == 0:
            output['color'] = colors.YELLOW

        #Count how many ntp servers are configured
        serverCount = 0
        for capacity in allCapacities:
            if capacity.startswith('NTP servers'):
                capacitySplit = capacity.split()
                serverCount += int(capacitySplit[3])
                output['text'] += f"{capacitySplit[0]} {capacitySplit[1]}: {capacitySplit[3]}\n"
        if serverCount == 0:
            output['color'] = colors.YELLOW
        
        #Count how many syslog servers are configured
        serverCount = 0
        for capacity in allCapacities:
            if capacity.startswith('Syslog hosts'):
                capacitySplit = capacity.split()
                serverCount += int(capacitySplit[3])
                output['text'] += f"{capacitySplit[0]} {capacitySplit[1]}: {capacitySplit[3]}\n"
        if serverCount == 0:
            output['color'] = colors.YELLOW

        return output

    def checkManagementACLs(self):
        """/c/sys/access/mgmt/add at the beginning of a line indicates it is a management ACL"""

        output = {'text' : ''}

        #Finds each line that looks like 
        ACLs = re.findall(r'(?<=\/c\/sys\/access\/mgmt\/add )([\d\D]*?)(?=\n)',self.raw,re.MULTILINE)
        for ACL in ACLs:
            output['text'] += ACL
        
        return output

    def checkRealServerStates(self):
        """/info/slb/dump looks for Real Servers that are not operational
        Returns a list of service entries."""

        #Entries look like this:
        #REAL_SERVER_NAME, aa:bb:cc:dd:ee:ff,  vlan 1, port 4, health inherit, DOWN
        #    Real Server Group SERVER_GROUP_NAME, health HEALTH_CHECK_NAME (runtime HTTPS)
        #    Virtual Services: 
        #    0: vport 12345
        #        virtual server: VirtualServerName, IP4 1.1.1.1

        out=[]
        output = {}

        #Grab the entire /info/slb/dump section of the tsdmp
        match = re.search(r'(?<=CLI Command \/info\/slb\/dump:\n)([\d\D]*?)(?=\n==)', self.raw)
        if not match:
            output['text'] = 'N/A'
            return output
        
        slbDump = match.group()
        #Grab the Real Server State section of slbDump
    
        realServerDump = re.search(r'(?<=Real server state:\n)([\d\D]*?)(?=\n\nFQDN server state:\n)', slbDump)
        if realServerDump != None:
            realServerDump = realServerDump.group()
        else:
            output['text'] = "No real servers found"
            return output

        #Carve realServerDump into a list of individual multi-line servers
        #Regex explanation:
        #Start of line (Non-whitespace character, [any characters] repeated)(Lookahead for newline non-whitespace or newline newline)
        realServers = re.findall(r'^(\S[\d\D]*?)(?=\n\S|\n\n)', realServerDump,re.MULTILINE)


        for server in realServers:
            #If the first line of the server entry doesn't end in UP, add it to output.
            if not server.split('\n')[0].endswith("UP"):
                out.append(server)



        # print("/info/slb/dump:  Real Servers that are not in the \'UP\' state:")
        # print("\n".join(out))
        # print('')

        if len(out) > 0:
            output['text'] = f'{len(realServers)} servers checked. {len(out)} {"is" if len(out)==1 else "are"} not operational:\n'
            output['text'] += "\n".join(out)
            if len(realServers) == len(out):
                output['color'] = colors.RED
            else:
                output['color'] = colors.YELLOW
        else:
            output['text'] = f'{len(realServers)} servers checked. All are operational.\n'
        return output
        #allLogs = matches.splitlines()

    def checkFQDNServerStates(self):
        """/info/slb/dump looks for Real Servers that are not up
        Returns a list of service entries."""

        #Entries look like this:
        #REAL_SERVER_NAME, aa:bb:cc:dd:ee:ff,  vlan 1, port 4, health inherit, DOWN
        #    Real Server Group SERVER_GROUP_NAME, health HEALTH_CHECK_NAME (runtime HTTPS)
        #    Virtual Services: 
        #    0: vport 12345
        #        virtual server: VirtualServerName, IP4 1.1.1.1

        out=[]
        output = {'text' : ''}

        #Grab the entire /info/slb/dump section of the tsdmp
        match = re.search(r'(?<=CLI Command \/info\/slb\/dump:\n)([\d\D]*?)(?=\n==)', self.raw)
        if match:
            slbDump = match.group()
        else:
            output['text'] = 'N/A'
            return output
        #Grab the Real Server State section of slbDump
        fqdnServerDump = re.search(r'(?<=FQDN server state:\n)([\d\D]*?)(?=\nVirtual server state:\n)', slbDump).group()
        
        #Carve realServerDump into a list of individual multi-line servers
        #Regex explanation:
        #Start of line (Non-whitespace character, [any characters] repeated)(Lookahead for newline non-whitespace or newline newline)
        fqdnServers = re.findall(r'^(\S[\d\D]*?)(?=\n\S|\n\n)', fqdnServerDump,re.MULTILINE)


        for server in fqdnServers:
            #If the first line of the server entry doesn't end in UP, add it to output.
            if not server.split('\n')[0].endswith("UP"):
                out.append(server)



        # print("/info/slb/dump:  FQDN Servers that are not in the \'UP\' state:")
        # print("\n".join(out))
        # print('')

        #output['text'] += f'{len(fqdnServers)} servers checked. {len(out)} are not UP:\n'
        #output['text'] += "\n".join(out)
        if len(fqdnServerDump) > 0:
            output['text'] = "FQDN Servers detected but script cannot process FQDN servers. Please check them manually."
            print("    FQDN Servers detected but script cannot process FQDN servers. Please check them manually.")
        return output
        #allLogs = matches.splitlines()
    def checkVirtualServerStates(self):
        """/info/slb/dump looks for servers and services that are not up
        Returns list of virtual servers"""

        out = ""
        output = {'text' : ''}

        #Grab the entire /info/slb/dump section of the tsdmp
        match = re.search(r'(?<=CLI Command \/info\/slb\/dump:\n)([\d\D]*?)(?=\n==)', self.raw)

        if match:
            slbDump = match.group()
        else:
            output['text'] = 'N/A'
            return output

        #Grab the Virtual Server State section of slbDump
        match = re.search(r'(?<=Virtual server state:\n)([\d\D]*?)(?:IDS group state:\n)([\d\D]*?)(?=\nRedirect filter state:\n)', slbDump)
        virtServerDump = match.group(1)
        IDSGroupDump = match.group(2)

        if len(IDSGroupDump) > 0:
            output['text'] = "IDS group(s) detected but not parsed. Please check IDS group state manually\n"
        
        #Carve virtServerDump into a list of individual multi-line servers
        if len(virtServerDump) > 1:
            #Regex explanation:
            #Start of line (Non-whitespace character, [any characters] repeated nongreedy)(Lookahead for newline non-whitespace or end of string)
            virtServers = re.findall(r'^([\d\D]+?)(?=\n\S|\Z)', virtServerDump,re.MULTILINE)
        else:
            output['text'] += "No Virtual servers found."
            return output
        
        downCount = 0
        for virtServer in virtServers:
            # print("----------------------")
            # print(virtServer)
            # print("=======================")
            #Break the virtual server into its component parts
            #Name: IP4 1.2.3.4, stuff
            #Additional Details
            #Virtual Services: List of virtual services
            virtServerDetails = re.search(r'(.+?): IP\d (.+?),([\s\S]*?)Virtual Services:\n([\s\S]*)',virtServer,re.MULTILINE)
            if virtServerDetails:
                #print(virtServerDetails)
                Name = virtServerDetails.group(1)
                IP = virtServerDetails.group(2)
                AdditionalDetails = virtServerDetails.group(3)
                VirtualServices = virtServerDetails.group(4)

                out += f'{IP}'
                #print("++++++")
                #print(Name,IP)
                #Find each virtual service in virtual services
                #virtServices = re.findall(r'    (.+?): rport (.+?),(.*)([\s\S]*?)(?:\Z|^    .+?: rp)', VirtualServices,re.MULTILINE)
                #virtServices = re.split(r'    (.+?: rport )',VirtualServices,re.MULTILINE)
                virtServices = re.split(r'    (.+?): rport (.+?),(.*)',VirtualServices,re.MULTILINE)
                #print(virtServices)
                i=1
                while i < len(virtServices):
                    ListenPort = virtServices[i]
                    i+=1
                    RealServerPort = virtServices[i]
                    i+=1
                    Extras = virtServices[i]
                    i+=1
                    RealServersString = virtServices[i]
                    i+=1
                    if Extras.count("UDP") > 0:
                        ListenPort += "_UDP"
                    ServerCount = 0
                    ServersUp = 0
                    #Regex returns an array of servers. Each server is an array with index 0=ServerName 1=ServerIP 2=HealthCheck 3=Latency 4=HealthCheckStatus
                    RealServers = re.findall(r'        (.*?): (.*?),.*?health (.*?), (.*?), (.*)',RealServersString,re.MULTILINE)
                    down=False
                    for server in RealServers:
                        ServerCount+=1
                        if server[4] == "UP":
                            ServersUp += 1
                        else:
                            down = True
                    if down:
                        downCount += 1
                    out += f' :{ListenPort}({ServersUp}/{ServerCount})'
                out += f' - {Name}\n'
            else:
                output['text'] += 'Unable to process virtual servers'
                output['color'] = colors.YELLOW
            

        output['text'] += f"{len(virtServers)} virtual servers checked. {downCount} have members not 'UP'\n\n"
        output['text'] += f'VIP :Port1(ServersUP/TotalServers) :Port2(ServersUP/TotalServers) - VirtName\n'
        output['text'] += out
        return output
    def listVirtualServers(self):
        
        return ""
    def checkFans(self):
        """Checks /info/sys/fan: for lines that do not contain Operational
        returns list of failed fans"""

        out = []
        output = {}

        match = re.search(r'(?<=^CLI Command \/info\/sys\/fan:\n)([\d\D]*?)(?=\n==)', self.raw,re.MULTILINE)
        
        if not match:
            output['text'] = "N/A"
            return output
        
        fans = re.findall(r'^[0-9]+[\d\D]*?(?=\n)', match.group(),re.MULTILINE)
        for fan in fans:
            if not 'Operational' in fan:
                out.append(fan)
                output['color'] = colors.RED
        
        if len(out) > 0:
            # print("/info/sys/fan: Possible fan failure detected.")
            # print('    ',"\n    ".join(out))
            output['text'] = f'{len(fans)} fans found. {len(out)} {"is" if len(out) == 1 else "are"} not operational.\n'
            output['text'] += "\n".join(out)
        else:
            #print("/info/sys/fan: All fans are operational.")
            output['text'] = f'{len(fans)} fans found. All Operational.'
        #print("")

        
        return output
    
    def checkTemp(self):
        """Checks /info/sys/temp: for lines that do not contain Operational
        returns a blank string if OK or the error message if not ok."""

        out = ''
        output = {}

        match = re.search(r'(?<=^CLI Command \/info\/sys\/temp:\n={106}\n)([\d\D]*?)(?=\nNote:)', self.raw,re.MULTILINE)
        
        if match:
            match = match.group()
        else:
            output['text'] = "N/A"
            return output

        output['text'] = match.replace(' has ',': ').replace('degree Celsius','°C').replace("Current device t","T")
        if not match.endswith("OK"):
            out = match
            output['color'] = colors.RED
        
        # if len(out) > 0:
        #     print("/info/sys/temp: Possible temperature issues")
        #     print('    ', out.replace('\n','    \n'))
        # else:
        #     print("/info/sys/temp: Temperature check OK")
        # print("")

        return output
    
    def getInterfaces(self):
        """List all device interface/subnet masks"""

        output = {'text':''}
        matches = re.findall(r"^/c/l3/if \d+(?:\n[ \t].+)+", self.raw, re.MULTILINE)
        for match in matches:
            addr_match = re.search(r"\baddr[ \t]+(\S+)", match)
            mask_match = re.search(r"\bmask[ \t]+(\S+)", match)
            prefix_match = re.search(r"\bprefix[ \t]+(\S+)", match)

            addr = addr_match.group(1) if addr_match else None
            mask = mask_match.group(1) if mask_match else None
            prefix = prefix_match.group(1) if prefix_match else None

            output['text'] += f"{addr} {mask if mask else prefix if prefix else ''}\n"
        
        return output
        
    def checkPortsEther(self):
        """Checks /stats/port <<<port number>>>/ether failure counters
        returns a dict in the format {1:[PortErrorCount,[Error1,Error2,...]]}"""

        out = {}
        output = {'text' : ''}

        #Port number can be 1 or 2 digits. Requires 2 regexes due to fixed with lookbehind requirement.
        ports = re.findall(r'(?<=CLI Command \/stats\/port [0-9]{1}\/ether\n={106}\n-{66}\n)([\d\D]*?)(?=\n\n)', self.raw,re.MULTILINE)
        ports += re.findall(r'(?<=CLI Command \/stats\/port [0-9]{2}\/ether\n={106}\n-{66}\n)([\d\D]*?)(?=\n\n)', self.raw,re.MULTILINE)

        for port in ports:
            lines = port.splitlines()
            
            portNum = re.search(r'(?<= port )([0-9]+?)(?=:$)', lines[0]).group()
            
            errors = []
            portErrorCount = 0
            for line in lines[1:]:
                lineErrorCount = re.search(r'(\S+?)(?=$)',line).group()
            
                if (lineErrorCount.isnumeric() and int(lineErrorCount) > 0):
                    portErrorCount += 1

                    #Remove the extra spaces in the error description
                    errors.append(" ".join(line.split()))
            if (portErrorCount > 0):
                out[portNum] = [portErrorCount, errors]
        
        # if (len(out) > 0):
        #     print('/stats/port <portNum>/ether: Errors detected:')
        #     for portNum in out:
        #         print(f'    /stats/port {portNum}/ether:')
        #         for error in out[portNum][1]:
        #             print('        ', error)
        # else:
        #     print("/stats/port <port number>/ether: No errors identified")
        # print("")

        #out contains a dict in the format {1:[PortErrorCount,[Error1,Error2,...]]}
        output['text'] = f'{len(ports)} ports checked. {len(out)} have errors{":" if len(out) > 0 else "."}\n'
        for port in out:
            output['text'] += f'    Port {port}: {out[port][0]} packet error{"s" if int(out[port][0]) > 1 else ""} identified\n'
            for error in out[port][1]:
                output['text'] += "        " + error + '\n'
                output['color'] = colors.YELLOW
                #output['text'] += "    " + out[port][error] + '\n'
        return output
    
    def checkPortsIf(self):
        """Checks /stats/port <<<port number>>>/if failure and discard counters
        returns a dict in the format {<PortNum>:[error%,discard%]}"""

        out = {}
        output = {'text' : ''}

        #Port number can be 1 or 2 digits. Requires 2 regexes due to fixed with lookbehind requirement.
        ports = re.findall(r'(?<=CLI Command \/stats\/port [0-9]{1}\/if\n={106}\n-{66}\n)([\d\D]*?)(?=\n\n)', self.raw,re.MULTILINE)
        ports += re.findall(r'(?<=CLI Command \/stats\/port [0-9]{2}\/if\n={106}\n-{66}\n)([\d\D]*?)(?=\n\n)', self.raw,re.MULTILINE)
        
        portsWithPacketsCount = 0
        for port in ports:
            lines = port.splitlines()
            
            portNum = re.search(r'(?<= port )([0-9]+?)(?=:$)', lines[0]).group()

            #Find total packet count
            match = re.search(r'(?<=UcastPkts:)(?:\s+)([0-9]+)(?:\s+)([0-9]+$)',port,re.MULTILINE)
            PacketCount = int(match.group(1)) + int(match.group(2))
            
            match = re.search(r'(?<=BroadcastPkts:)(?:\s+)([0-9]+)(?:\s+)([0-9]+$)',port,re.MULTILINE)
            PacketCount += int(match.group(1)) + int(match.group(2))

            match = re.search(r'(?<=MulticastPkts:)(?:\s+)([0-9]+)(?:\s+)([0-9]+$)',port,re.MULTILINE)
            PacketCount += int(match.group(1)) + int(match.group(2))

            #Find total discard count
            match = re.search(r'(?<=Discards:)(?:\s+)([0-9]+)(?:\s+)([0-9]+$)',port,re.MULTILINE)
            DiscardCount = int(match.group(1)) + int(match.group(2))

            #Find total error count
            match = re.search(r'(?<=Errors:)(?:\s+)([0-9]+)(?:\s+)([0-9]+$)',port,re.MULTILINE)
            ErrorCount = int(match.group(1)) + int(match.group(2))

            if (PacketCount > 0):
                portsWithPacketsCount += 1
                DiscardPercent = (DiscardCount / PacketCount) * 100
                ErrorPercent = (ErrorCount / PacketCount) * 100
                #Report all errors
                if ((DiscardCount + ErrorCount) > 0):
                #    output[portNum] = [PacketCount, DiscardCount, ErrorCount]
                    #out[portNum] = [DiscardPercent, ErrorPercent,PacketCount,ErrorCount,DiscardCount]
                    out[portNum] = [ErrorPercent, DiscardPercent, PacketCount, ErrorCount, DiscardCount]

                ##Report ports with >0.1% errors:
                if ((DiscardPercent + ErrorPercent) >= 0.0001):
                    output['color'] = colors.YELLOW
                    if ((DiscardPercent + ErrorPercent) >= 1):
                        output['color'] = colors.RED
                #out[portNum] = [DiscardPercent, ErrorPercent,PacketCount,ErrorCount,DiscardCount]
        
        output['text'] = f'{len(ports)} ports checked. {portsWithPacketsCount} have seen packets.\n'
        if (len(out) > 0):
            #print("/stats/port <port number>/if: > 0.0001% interface errors detected for the following ports:")
            output['text'] += "interface errors were detected for the following ports:\n"
            for port in out:
                #print(f'    Port {port} Errors: {out[port][0]}% Discards: {out[port][1]}%' + \
                #      f'        Packets: {out[port][2]} Errors: {out[port][3]} Discards: {out[port][4]}\n' \
                #      )
                #output['text'] += f'    Port {port} errors: {round(out[port][0],6)}% Discards: {round(out[port][1],6)}%\n' + \
                #                  f'        Packets: {out[port][2]} Errors: {out[port][3]} Discards: {out[port][4]}\n'
                output['text'] += f'    Port {port} errors: {out[port][0]:.3f}% Discards: {out[port][1]:.3f}%\n' + \
                                  f'        Packets: {out[port][2]} Errors: {out[port][3]} Discards: {out[port][4]}\n'

        else:
            #print("No significant (>0.0001% of packets) interface errors or discards detected.")
            output['text'] += 'No interface errors detected.'
        #print("")
        
            

        return output