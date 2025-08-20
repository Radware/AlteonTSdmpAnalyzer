#Alteon TSdmp Analyzer

# Owner/Maintainer

	Steve Harris - Steven.Harris@radware.com

# About

	This script parses a directory full of TSdmp files, identifies common problem areas, and outputs the findings to an .xls file.

	Input: Place tsdmp files and\or TechData.tgz files into the .\TSDmp\ folder or .\TSDmp\<Any Subfolder>\
		Note: The 'NoProcess' Subfolder will not be processed. 
	Output: .\Report\TSdmpReport.<Date>.xlsx
	
#Prerequesites
	Requires the openpyxl library. 'pip install openpyxl' to download.
	
# How to run

	1. Place Alteon TSdmp files into the .\TSdmp\ folder
	2. Run the script
		python TSdmpAnalyzer.py
	3. View your report under .\Report\TSdmpReport.<Date>.xlsx

# Config audit checks scope
	The script will pull and output the following data:
	1.	Name, - The file name of the TSdmp file
	2.	Management IP, - Self explanatory
	3.	BaseMac, - Self explanatory
	4.	Model, - Appliance Model name
	5.	SWVersion, - The version of code from which the TSdmp was exported
	6.	Date, - The date the TSdmp file was exported.
	7.	Appliance Uptime, - Time since last reboot
	8.	List long SSHSessions, - Check for long lasting SSH sessions which could be indicative of a problem
	9.	PIP Allocation Failures, - Cell will be highlighted in red if allocation failures exist
	10.	LicenseUtilization, - Cell will be highlighted in yellow if any service is using > 60% of it's licenced limit
	11.	SessionTableAllocation, - Recommended to be set to 50%. Will highlight in yellow if not 50%
	12.	PanicDumps, - List any Panic dumps located on the appliance.
	13.	AlarmingSyslogs, - TSDmp contains the latest 200 syslog entries, removing duplicates. The script displays all that are WARNING, ALERT, or CRITICAL. Output is <count> <severity> <Log>
	14.	RealServerStates, - Display any real servers that are not UP
	15.	Virtual Server States, - Display all virtual services that have members that are not UP
	16.	Fans, - Display current fan state. Highlights red if not Operational
	17.	Temperature, - Display current temperature state. Highlights red if current temperature is not OK
	18.	Ports (Ether), Checks '/stats/port <port number>/ether' failure counters. Lists ports that have failures > 0
	19.	Ports (If), Checks '/stats/port <port number>/if' failure and discard counters. Highlights yellow if failure % is >= .0001% of packets. Red if > 1%
	Config sanity:
		Stale/Orphaned items:
			1. servers that are not in groups
			2. groups that have no servers 
			3. groups where the text 'group <groupname><eol>' only exists in the file once (it's definition).
			4. /c/slb/sslpol <policyname> where the text 'sslpol <policyname><eol>' only exists in the file once (it's definition).
			5. SSL Certs and intermca's where 'cert <certname><eol>' only exists in the file once (it's definition).
			6. Appshape++ scripts where the following doesn't exist:
				.../Appshape
				    add <#> <ScriptName>


# Version control
	v0.10.0 (20 August 2025) 
		Added Configuration checking.
			Stale/Orphaned: Servers, Groups, SSL Policies, SSL Certificates, Intermediate CA certs, and Appshape++ scripts
	v0.9.0 - Misc bugfixes
	v0.8.0 - Initial Release 


# Known Limitations
- Does not check 'FQDN server state' or 'IDS group state'. It should identify if any FQDN or IDS groups exist and notify you in the report to check manually.