import os, subprocess, json, re
import requests
import streamlit as st
from streamlit.components.v1 import html as st_html

st.set_page_config(page_title="FluxLab Dashboard", layout="wide")
st.title("FluxLab – Live DNS & Service Glance")

DIG = "/usr/bin/dig"  # installed by dnsutils in Debian/Ubuntu images

def run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception as e:
        return f"(error running {' '.join(cmd)}: {e})"

def strip_url(s: str) -> str:
    s = s.strip()
    s = re.sub(r'^[a-z]+://', '', s, flags=re.I)  # remove scheme
    s = s.split('/',1)[0]                          # remove path
    return s

domain = os.environ.get("FLUXLAB_DOMAIN", "sim.local")

# Detect resolvers from /etc/resolv.conf
ns: list[str] = []
try:
    with open("/etc/resolv.conf") as f:
        for line in f:
            if line.startswith("nameserver "):
                ns.append(line.split()[1].strip())
except Exception:
    pass

st.subheader("Resolvers (/etc/resolv.conf)")
try:
    with open("/etc/resolv.conf") as f:
        st.code(f.read())
except Exception:
    st.code("(failed to read /etc/resolv.conf)")

q_default = f"fluxynet.{domain}"
q = strip_url(st.text_input("Query (hostname only)", q_default))

colA, colB = st.columns(2)

with colA:
    st.write(f"**{DIG} +short {q}**")
    st.code(run([DIG, "+short", q]) or "(no answer)")

with colB:
    if ns:
        st.write(f"**{DIG} +short @{ns[0]} {q}**")
        st.code(run([DIG, "+short", f"@{ns[0]}", q]) or "(no answer)")
    else:
        st.warning("No nameservers detected in /etc/resolv.conf")

st.divider()
st.subheader("docker compose ps (json)")
# This will usually be empty unless you mount /var/run/docker.sock and the CLI;
# keep it best-effort.
ps_json = run(["bash","-lc","docker compose ps --format json || true"])
try:
    st.json(json.loads(ps_json) if ps_json else [])
except Exception:
    st.write("(unavailable)")

st.divider()
st.subheader("HTTP Fetch from dns_client_test")
fetch_col1, fetch_col2 = st.columns([3,1])
with fetch_col1:
    raw_url = st.text_input("URL", f"http://{q}")
with fetch_col2:
    timeout = st.number_input("Timeout (s)", min_value=1.0, max_value=30.0, value=5.0, step=0.5)

if st.button("Fetch"):
    target = raw_url.strip()
    if not target:
        st.warning("Enter a URL or hostname.")
    else:
        if not re.match(r"^https?://", target, flags=re.I):
            target = "http://" + target
        try:
            resp = requests.get(target, timeout=timeout)
            st.success(f"{resp.status_code} {resp.reason}")
            st.write("**Headers**")
            st.json(dict(resp.headers))

            content_type = resp.headers.get("Content-Type","").lower()
            body = resp.text
            st.write("**Body Preview**")
            if "html" in content_type:
                st_html(body, height=400, scrolling=True)
                st.caption("Iframe rendering depends on the target allowing embedding; if it stays blank, the server likely denied it.")
                st_html(
                    f'<iframe src="{target}" style="width:100%;height:420px;border:1px solid rgba(148,163,184,0.35);border-radius:12px;background:#0f172a;" sandbox="allow-same-origin allow-scripts allow-forms allow-popups" referrerpolicy="no-referrer"></iframe>',
                    height=440,
                    scrolling=True,
                )
            else:
                st.code(body[:8000] or "(empty body)")
        except Exception as exc:
            st.error(f"Request failed: {exc}")
