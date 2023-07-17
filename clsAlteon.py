
import codecs
import tarfile
import re

class colors:
    RED = 'FFC7CE'#00FF0000'
    YELLOW = 'FFEB9C'#'00FFFF00'

#loads a file to a string, nothing else
#todo:
##Populate variables with tuple of interfaces, groups, real servers, virtual services, etc
##Parse config string for common errors
##Maybe Later: connect to appliance and parse health checks
class clsAlteonConfig:
    def __init__(self,path,file):
        self.fileName=file
        self.hostname="N/A"
        self.mgmtIP="N/A"
        with open(path + file, 'r') as f:
            self.rawConfig = f.read()

        #Replace multi-line config entries with single line equivilant. For example
        #/c/slb/real WebServer1/ena
        #   name "Web Application Server 1"
        #Becomes
        #/c/slb/real WebServer1/ena/name "Web Application Server 1"
        self.config = self.rawConfig.replace("\n\t", '/') 

#Opens a TechData.tgz. Extracts and analyzes the tsdmp file contained within.
#Todo, VX files are in different places than standalone alteon. Take this into account
class clsTechData:#Incomplete
    def __init__(self,path,file):
        self.filename=file
        self.outputCells = []
        #Open the .tgz file and place specific files into variables
        with tarfile.open(path + file,'r:gz') as tar:
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
            extractedFile = tar.extractfile("/disk/Alteon/tsdmp")
            self.TSdmp = clsTSdmp(codecs.getreader("utf-8")(extractedFile).read(), file)
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

    def analyze(self):
        '''Analyzes the tsdmp file for various common issues'''

        ##Enable colored console output
        #os.system('color')

        self.Name = {'text': self.fileName}
        self.IP = self.getmgmtIP()
        self.BaseMac = self.getBaseMac()
        self.Model = self.getModel()
        self.SWVersion = self.getSWVersion()
        self.Date = self.getDate()
        self.Uptime = self.getUptime()
        #ToDo: Change these from print to a file output
        self.SSHSessions = self.checkSSHSessions()
        self.AllocationFailures = self.checkAllocationFailures()
        self.LicenseUtilization = self.checkLicenseUtilization()
        self.SessionTableAllocation = self.checkSessionTableAllocation()
        self.PanicDumps = self.checkPanicDumps()
        self.AlarmingSyslogs = self.checkAlarmingSyslogs()
        self.RealServerStates = self.checkRealServerStates()
        #checkFQDNServerStates doesn't correctly parse yet.
        checkFQDNOut = self.checkFQDNServerStates()
        self.RealServerStates['text'] += "\n" + checkFQDNOut['text']
        print("'FQDN server state:' not checked. Must be checked manually.")
        self.VirtualServerStates = self.checkVirtualServerStates()
        print("'IDS group state:' not checked. Must be checked manually.")
        self.Fans = self.checkFans()
        self.Temp = self.checkTemp()
        self.PortsEther = self.checkPortsEther()
        self.PortsIf = self.checkPortsIf()

        
        return [ 
            self.Name,
            self.IP,
            self.BaseMac,
            self.Model,
            self.SWVersion,
            self.Date,
            self.Uptime,
            self.SSHSessions,
            self.AllocationFailures,
            self.LicenseUtilization,
            self.SessionTableAllocation,
            self.PanicDumps,
            self.AlarmingSyslogs,
            self.RealServerStates,
            self.VirtualServerStates,
            self.Fans,
            self.Temp,
            self.PortsEther,
            self.PortsIf
        ]
    def getmgmtIP(self):
        #CLI Command /info/sys/mgmt:
        match = re.search(r'(?<=^CLI Command /info/sys/mgmt:\n={106}\n)([\d\D]+?)(?=\n====)', self.raw, re.MULTILINE).group()
        ip = re.search(r'(?<=^Interface information:\n )([\d\D]+?)(?=\s)',match,re.MULTILINE).group()
        print(ip)

        return {'text' : ip}
    
    def getBaseMac(self):
        """Returns the appliance base MAC address"""
        
        output = {}

        output['text'] = re.search(r'(?<=Base MAC: )([\d\D]+?$)', self.raw, re.MULTILINE).group()
        print(f'Base MAC: {output["text"]}')
        return output
    
    def getModel(self):
        """Returns the appliance model name"""
        
        output = {}

        output['text'] = re.search(r'(?<=Memory profile is)(?:.+\n\n)([\d\D]+?$)', self.raw, re.MULTILINE).group(1)
        print(f'Base MAC: {output["text"]}')
        return output
    def getSWVersion(self):
        """Returns the OS SWVersion"""
                
        output = {}

        output['text'] = re.search(r'(?<=Software Version )([\d\D]+?)(?= Image ID )', self.raw, re.MULTILINE).group()
        print(f'Running Software Version: {output["text"]}')
        return output
    def getDate(self):
        """Returns the tsdmp datestamp"""
        
        output = {}

        output['text'] = re.search(r'(?<=^TIMESTAMP:  )([\d\D]+?)(?= )', self.raw, re.MULTILINE).group()
        print(f'TSDmp datestamp: {output["text"]}')
        return output
    
    def getUptime(self):
        """Returns the tsdmp Time since last reboot"""
        
        output = {}

        output['text'] = re.search(r'(?<=^Switch is up )([\d\D]+?minutes)(?= )', self.raw, re.MULTILINE).group()
        print(f'Time since last reboot: {output["text"]}')
        return output

    def checkSSHSessions(self):
        """Checks the tsdmp for long SSH sessions"""
        output = {}
        #Regex explanation: 
        # (Lookbehind for '/who: <Newline> <84 = in a row> <newline>)(Match any character including newlines, repeat, nongreedy)(Lookahead for <newline><newline>)
        print("Checking SSH Sessions")
        try:
            slashWho = re.search(r'(?<=\/who: \n={84}.\n)([\d\D]*?)(?=\n\n)', self.raw).group()
        except:
            slashWho = []
    
        #ToDo: Prune self.slashWho to only contain long ssh sessions
        output['text'] = f'{len(slashWho.splitlines())} entries found{":" if len(slashWho) > 0 else "."}\n{slashWho}'

        #Display to console
        if len(slashWho) > 0:
            #Todo - perform pruning of self.slashWho and only return data for >1 hour entries. Output needs to be reformatted into a raw array
            print('/who: Possible long SSH entries. Long (multiple hour) SSH entries can be indicative of an issue:')
            for line in output:
                print('    ', line)
        else:
            print('/who: No SSH sessions found')
        print('')

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

            #if there are a nonzero number of failures, include the PIP array in the failurePIPs array.
            if PIPdata[3] != '0':
                failurePIPs.append(PIPdata)

        output['text'] = f'{len(PIPs)} pips checked. {len(failurePIPs)} failed.'
        if len(failurePIPs) > 0:
            print("/stats/slb/dump: PIP failures detected:\n" + \
                "     [<PIP>, <free>, <used>, <failures>]")
            
            for PIP in failurePIPs:
                print('    ', PIP)
                output['text'] += f'{PIP[0]}: {PIP[3]} failures\n'
            output['color'] = colors.RED
        else:
            if len(PIPs) > 0:
                print(f"/stats/slb/dump: {len(PIPs)} PIPs found. No PIP failures detected.")
            else:
                print("/stats/slb/dump: No PIPs detected")
        print('')
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
        matches = re.search(r'(?<=Capacity Utilization\n====================\n)([\d\D]*?)(?=\n\n)', self.raw).group()
        features = matches.splitlines()

        #the first 2 lines in features are headings. Loop through the rest
        for feature in features[2:]:
            #Removes spaces between digit and unit symbol. ex: '4 Gbps' becomes '4Gbps'
            line = re.sub(r'(?<=\d) (?=\D)', "", feature)
            line = line.split()

            #Compares Licensed limit with PeakObserved. Returns True if Peak is > (Max * 60%)
            if self.__isOverThreshold(line[1], line[2]):
                 #Insert space between number and units label. Ex: '6Gbps' becomes '6 Gbps'
                for i in range(1,4):
                    line[i] = re.sub(r'(?<=\d)([a-zA-Z])', r' \1', line[i])
                overThresholdLicenses.append(line)
                output['color'] = colors.RED

        #Display to console
        if len(overThresholdLicenses) > 0:
            print("Observed traffic exceeds 60% of licensed maximum for the following licenses:")
            print("     [Feature, Capacity, PeakUsage, CurrentUsage]")
            for line in overThresholdLicenses:
                print('    ', line)
            output['color'] = colors.YELLOW
        else:
            print("License check passed. No traffic exceeded 60% of licensed limit.")
        print('')
        #print(overThresholdLicenses)
        
        output['text'] =  "\n".join([f.strip() for f in features[2:]])
        return output

    def __isOverThreshold(self,limit,peakObserved):
        """Compares limit to peakObserved. Returns true if peakObserved is > 60% of limit. False otherwise"""
        
        #Unlimited licenses will never be over limit
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
        #Lines now contains [==========, HW type, Mem Capacity, Sess Table Setting, Data Table Setting, Peak Sessions, Peak AX Sessions, Peak Data Table]
        
        #Grab the % value from line3 (session table setting)
        value = re.search(r'(?<= )(\d*?)(?=%$)', lines[3]).group()
        
        #Display to console and return
        if value != '50':
            print('/stats/slb/peakinfo: It is recommended that the session table value is set to 50%. The current value is:')
            print('    ', lines[3])
            output['color'] = colors.YELLOW
        else:
            print('/stats/slb/peakinfo: session table value is correct (50%)')
        print('')

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

        matches = re.search(r'(?<=Show the list of available core dump files from CLI command /maint/coredump/list:\n)([\d\D]*?)(?=\n\n\n)', self.raw).group()
        lines = matches.splitlines()
        
        #the first line contains '=======' the rest are relevant
        for line in lines[2:]:
            if not line.strip().startswith("No"):
                out.append(line.strip())
        
        #Display to console
        if len(out) > 0:
            print("/maint/lsdmp and /maint/coredump/list: The following panic dumps were found:")
            for line in out:
                print('    ',line)
        else:
            print("/maint/lsdmp and /maint/coredump/list: No panic dumps were found.")
        print('')

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
                stamplessLog = re.search(r'(ALERT|CRITICAL|WARNING)\s+.*$', log).group()
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
            
            print("/info/sys/log: Latest 200 syslog entries contain entries that could require attention:")
            for log in logDict:
                print('    ', f'{logDict[log][1]} - Repeated {logDict[log][0]} times')
                #With timestamp: output['text'] += f'{logDict[log][0]}: {logDict[log][1]}'
                output['text'] += f'{logDict[log][0]}: {log}\n'
        else:
            print("/info/sys/log: Latest 200 syslog entries searched. No ALERT, CRITICAL, or WARNING messages found.")
        print('')

        #Return a list instead of a dictionary.
        #return list(logDict.items())
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
        slbDump = re.search(r'(?<=CLI Command \/info\/slb\/dump:\n)([\d\D]*?)(?=\n==)', self.raw).group()
        
        #Grab the Real Server State section of slbDump
        realServerDump = re.search(r'(?<=Real server state:\n)([\d\D]*?)(?=\n\nFQDN server state:\n)', slbDump).group()
        
        #Carve realServerDump into a list of individual multi-line servers
        #Regex explanation:
        #Start of line (Non-whitespace character, [any characters] repeated)(Lookahead for newline non-whitespace or newline newline)
        realServers = re.findall(r'^(\S[\d\D]*?)(?=\n\S|\n\n)', realServerDump,re.MULTILINE)


        for server in realServers:
            #If the first line of the server entry doesn't end in UP, add it to output.
            if not server.split('\n')[0].endswith("UP"):
                out.append(server)



        print("/info/slb/dump:  Real Servers that are not in the \'UP\' state:")
        print("\n".join(out))
        print('')

        output['text'] = f'{len(realServers)} servers checked. {len(out)} are not operational:\n'
        output['text'] += "\n".join(out)
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
        slbDump = re.search(r'(?<=CLI Command \/info\/slb\/dump:\n)([\d\D]*?)(?=\n==)', self.raw).group()
        
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



        print("/info/slb/dump:  FQDN Servers that are not in the \'UP\' state:")
        print("\n".join(out))
        print('')

        #output['text'] += f'{len(fqdnServers)} servers checked. {len(out)} are not UP:\n'
        #output['text'] += "\n".join(out)
        if len(fqdnServerDump) > 0:
            output['text'] = "FQDN Servers detected but script cannot process FQDN servers. Please check them manually."
            print("FQDN Servers detected but script cannot process FQDN servers. Please check them manually.")
        return output
        #allLogs = matches.splitlines()
    def checkVirtualServerStates(self):
        """/info/slb/dump looks for servers and services that are not up
        Returns list of virtual servers"""

        out = []
        output = {'text' : ''}

        #Grab the entire /info/slb/dump section of the tsdmp
        slbDump = re.search(r'(?<=CLI Command \/info\/slb\/dump:\n)([\d\D]*?)(?=\n==)', self.raw).group()
        
        #Grab the Virtual Server State section of slbDump
        match = re.search(r'(?<=Virtual server state:\n)([\d\D]*?)(?:IDS group state:\n)([\d\D]*?)(?=\nRedirect filter state:\n)', slbDump)
        virtServerDump = match.group(1)
        IDSGroupDump = match.group(2)

        if len(IDSGroupDump) > 0:
            output['text'] = "IDS group(s) detected but not parsed. Please check IDS group state manually\n"
        
        #Carve virtServerDump into a list of individual multi-line servers
        #Regex explanation:
        #Start of line (Non-whitespace character, [any characters] repeated)(Lookahead for newline non-whitespace or end of string)
        virtServers = re.findall(r'^([\d\D]*?)(?=\n\S|\Z)', virtServerDump,re.MULTILINE)

        for virtServer in virtServers:
            serverDown = False
            #Find each virtual service in virtual services
            virtServices = re.findall(r'(?<=        Real Servers:\n)([\d\D]*?)(?=    [azAZ0-9]|\Z)', virtServer,re.MULTILINE)
            for virtService in virtServices:
                #Find the first line of each real server within the virtual service
                realServers = re.findall(r'(?<=^        )([a-zA-Z0-9][\d\D]*?)(?=\n)', virtService,re.MULTILINE)
                for server in realServers:
                    if not server.endswith("UP"):
                        serverDown = True
                        break
            if serverDown:
                
                out.append(virtServer)

        #Todo: Possibly refine to show virtual servers with members down and display the up/down counts rather than the entire list.
        print("/info/slb/dump: Virtual Servers that contain members not in the \'UP\' state:")
        print(re.sub(r'(^)', r'    ', "\n".join(out), 0, re.MULTILINE))
        print("")

        output['text'] += f'{len(virtServers)} virtual servers checked. {len(out)} have members not \'UP\'\n'
        output['text'] += "\n".join(out).replace('\t','    ').replace('\n\n','\n')
        return output
    
    def checkFans(self):
        """Checks /info/sys/fan: for lines that do not contain Operational
        returns list of failed fans"""

        out = []
        output = {}

        match = re.search(r'(?<=^CLI Command \/info\/sys\/fan:\n)([\d\D]*?)(?=\n==)', self.raw,re.MULTILINE).group()

        fans = re.findall(r'^[0-9]+[\d\D]*?(?=\n)', match,re.MULTILINE)
        for fan in fans:
            if not 'Operational' in fan:
                out.append(fan)
                output['color'] = colors.RED
        
        if len(out) > 0:
            print("/info/sys/fan: Possible fan failure detected.")
            print('    ',"\n    ".join(out))
            output['text'] = f'{len(fans)} fans found. {len(out)} {"is" if len(out) == 1 else "are"} not operational.\n'
            output['text'] += "\n".join(out)
        else:
            print("/info/sys/fan: All fans are operational.")
            output['text'] = f'{len(fans)} fans found. All Operational.'
        print("")

        
        return output
    
    def checkTemp(self):
        """Checks /info/sys/temp: for lines that do not contain Operational
        returns a blank string if OK or the error message if not ok."""

        out = ''
        output = {}

        match = re.search(r'(?<=^CLI Command \/info\/sys\/temp:\n={106}\n)([\d\D]*?)(?=\nNote:)', self.raw,re.MULTILINE).group()

        output['text'] = match
        if not match.endswith("OK"):
            out = match
        
        if len(out) > 0:
            print("/info/sys/temp: Possible temperature issues")
            print('    ', out.replace('\n','    \n'))
            output['color'] = colors.RED
        else:
            print("/info/sys/temp: Temperature check OK")
        print("")

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
        
        if (len(out) > 0):
            print('/stats/port <portNum>/ether: Errors detected:')
            for portNum in out:
                print(f'    /stats/port {portNum}/ether:')
                for error in out[portNum][1]:
                    print('        ', error)
        else:
            print("/stats/port <port number>/ether: No errors identified")
        print("")

        #out contains a dict in the format {1:[PortErrorCount,[Error1,Error2,...]]}
        output['text'] = f'{len(ports)} ports checked. {len(out)} have errors{":" if len(out) > 0 else "."}\n'
        for port in out:
            output['text'] += f'    Port {port}: {out[port][0]} packet error{"s" if int(out[port][0]) > 1 else ""} identified\n'
            for error in out[port][1]:
                output['text'] += "        " + error + '\n'
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
                    out[portNum] = [DiscardPercent, ErrorPercent,PacketCount,ErrorCount,DiscardCount]

                ##Report ports with >0.1% errors:
                if ((DiscardPercent + ErrorPercent) >= 0.0001):
                    output['color'] = colors.YELLOW
                    if ((DiscardPercent + ErrorPercent) >= 1):
                        output['color'] = colors.RED
                #out[portNum] = [DiscardPercent, ErrorPercent,PacketCount,ErrorCount,DiscardCount]
        
        output['text'] = f'{len(ports)} ports checked. {portsWithPacketsCount} have seen packets.\n'
        if (len(out) > 0):
            print("/stats/port <port number>/if: > 0.0001% interface errors detected for the following ports:")
            output['text'] += "interface errors were detected for the following ports:\n"
            for port in out:
                print(f'    Port {port} Errors: {out[port][0]}% Discards: {out[port][1]}%' + \
                      f'        Packets: {out[port][2]} Errors: {out[port][3]} Discards: {out[port][4]}\n' \
                      )
                output['text'] += f'    Port {port} errors: {round(out[port][0],6)}% Discards: {round(out[port][1],6)}%\n' + \
                                  f'        Packets: {out[port][2]} Errors: {out[port][3]} Discards: {out[port][4]}\n'
                
        else:
            print("No significant (>0.0001% of packets) interface errors or discards detected.")
            output['text'] += 'No interface errors detected.'
        print("")
        
            

        return output