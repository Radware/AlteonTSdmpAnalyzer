import re
from typing import Dict, List, Any

def parse_hier_config(text: str) -> Dict[str, Any]:
    """
    Builds a nested dict from a config like:
      /c/sys/mmgmt
          addr 0.0.0.0
          ...
      /c/sys/addr
          asdf
      /c/asdf
          more stuff

    Structure:
      {
        "c": {
          "sys": {
            "mmgmt": {"__lines__": ["addr 0.0.0.0", "mask 0.0.0.0", ...]},
            "addr":  {"__lines__": ["asdf"]},
          },
          "asdf": {"__lines__": ["more stuff"]},
        }
      }
    """
    root: Dict[str, Any] = {}
    current_node: Dict[str, Any] | None = None

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue

        if line.startswith("/"):  # a new path header
            parts = [p for p in line.strip().split("/") if p]
            node = root
            for p in parts:
                node = node.setdefault(p, {})
            node.setdefault("__lines__", [])
            current_node = node
        else:
            # indented content line for the most recent path
            if current_node is not None:
                current_node.setdefault("__lines__", []).append(line.strip())

    return root
cfg = r"""/c/sys/mmgmt
        addr 0.0.0.0
        mask 0.0.0.0
        broad 255.255.255.255
        gw 0.0.0.0
        addr6 2001:2::3
        prefix6 64
        gw6 2001:2::1
        ena
        dns mgmt
        ocsp mgmt
        cdp mgmt
        smtp mgmt
        snmp mgmt
        syslog mgmt
        tftp mgmt
        wlm mgmt
        report mgmt
        wsradius mgmt
        wsldap mgmt
        awsignal mgmt
/c/sys/addr
        asdf
/c/asdf
        more stuff
"""

tree = parse_hier_config(cfg)
pass