import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.mcp_security import validate_remote_url, validate_static_headers, resolve_remote_addresses

def main():
    try: resolve_remote_addresses('x',443,lambda h,p: [])
    except ValueError: pass
    for vals in ([], ['93.184.216.34','10.0.0.1']):
        try: resolve_remote_addresses('x',443,lambda h,p,v=vals:v)
        except ValueError: pass
        else: assert vals and vals[0]=='93.184.216.34'
    assert resolve_remote_addresses('x',443,lambda h,p:['93.184.216.34']) == ['93.184.216.34']
    blocked = ["http://mcp.example/mcp", "https://localhost/mcp", "https://127.0.0.1/mcp", "https://[::1]/mcp", "https://169.254.169.254/latest/meta-data", "https://metadata.google.internal/mcp", "https://user:pass@example.com/mcp"]
    for value in blocked:
        try:
            validate_remote_url(value, resolver=lambda h,p: ["93.184.216.34"])
        except ValueError:
            pass
        else:
            raise AssertionError(value)
    assert validate_remote_url("https://mcp.example.com/mcp", resolver=lambda h,p: ["93.184.216.34"]) == "https://mcp.example.com/mcp"
    # Resolver policy is evaluated on every validation, including stateful answers.
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    resolver = lambda h,p: next(answers)
    validate_remote_url("https://mcp.example.com/mcp", resolver=resolver)
    try:
        validate_remote_url("https://mcp.example.com/mcp", resolver=resolver)
    except ValueError:
        pass
    else:
        raise AssertionError("private second resolution accepted")
    assert validate_remote_url("https://xn--bcher-kva.example/mcp", resolver=lambda h,p: ["93.184.216.34"]) == "https://xn--bcher-kva.example/mcp"
    for value in ("https://[fe80::1%25eth0]/mcp", "https://./mcp", "https://bad\r\n.example/mcp"):
        try: validate_remote_url(value, resolver=lambda h,p: ["93.184.216.34"])
        except ValueError: pass
        else: raise AssertionError(value)
    # getaddrinfo's single 5-tuple form is accepted.
    assert validate_remote_url("https://mcp.example.com/mcp", resolver=lambda h,p: (2, 1, 6, "", ("93.184.216.34", p)))
    assert validate_static_headers({"Authorization": "Bearer x"}) == {"Authorization": "Bearer x"}
    for headers in ({"Host":"x"},{"Cookie":"x"},{"Mcp-Session-Id":"x"},{"Connection":"x"},{"bad name":"x"},{"X":"a\r\nb"},{"X":"x"*8193},{"X":"1","x":"2"}):
        try: validate_static_headers(headers)
        except ValueError: pass
        else: raise AssertionError(headers)
    print("mcp url policy checks passed")

if __name__ == "__main__": main()
