#!/usr/bin/env python3
"""Change a MyNixOS flake through api.mynixos.com instead of the website.

Usage: python3 -I mynixos.py [--flake OWNER/FLAKE] COMMAND ...

  setting get <option> [--target T]
  setting set <option> --file F [--target T]
  package add <option> <package> [--target T] [--package-flake nixpkgs]
  input update <name>
  release [--wait]

The flake comes from --flake or MYNIXOS_FLAKE. Writes need a Firebase ID
token for the signed-in MyNixOS user: MYNIXOS_ID_TOKEN, or a refresh token,
which is exchanged for one, from MYNIXOS_REFRESH_TOKEN or from the output of
--token-command / MYNIXOS_TOKEN_COMMAND (such as a keychain or `pass` lookup,
run only for commands that need a token). Tokens are never printed.

The API is undocumented: every request shape here was read from the
website's own JavaScript, so any call can break when the site changes.

Layout: the configuration is read once into an immutable Config; the
functions under "Documents" are pure, taking and returning plain values;
only the functions under "Effects" touch the network, files or processes,
and the commands compose the two and return their output as text.
"""

import argparse
import datetime
import functools
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable, Iterator, NamedTuple, Optional, Tuple

API = "https://api.mynixos.com"
WEB = "https://mynixos.com"
JSON_API = "application/vnd.api+json"
USER_AGENT = "mynixos-api-skill/1 (+python urllib)"
VERSION_INCLUDE = (
    "?include=inputs.targetFlakeRef.flakeVersion,"
    "nixosModules.imports.flakeInput,nixosModules.imports.targetModule,"
    "nixosModules.settings.option,nixosModules.settings.packageRefs.package"
)
SETTING_INCLUDE = "?include=option,packageRefs.package"


class ApiError(Exception):
    pass


# Configuration


class Config(NamedTuple):
    flake: Optional[str]
    id_token: Optional[str]
    refresh_token: Optional[str]
    token_command: Optional[str]
    firebase_api_key: Optional[str]


def config_from(env, args) -> Config:
    return Config(
        flake=args.flake or env.get("MYNIXOS_FLAKE"),
        id_token=env.get("MYNIXOS_ID_TOKEN") or None,
        refresh_token=env.get("MYNIXOS_REFRESH_TOKEN") or None,
        token_command=args.token_command or env.get("MYNIXOS_TOKEN_COMMAND") or None,
        firebase_api_key=env.get("MYNIXOS_FIREBASE_API_KEY") or None,
    )


def flake_fqn(flake: Optional[str]) -> str:
    if not flake or flake.count("/") != 1:
        raise ApiError("give the flake as --flake OWNER/FLAKE or MYNIXOS_FLAKE")
    return "/" + flake.strip("/")


# Documents: pure functions over the API's JSON:API documents and pages


def latest_draft_fqn(flake_doc, flake: str) -> str:
    """The fqn of the flake's newest mutable (draft) version."""
    drafts = [
        v
        for v in flake_doc.get("included", [])
        if v["type"] == "nix_flake_versions" and v["attributes"].get("isMutable")
    ]
    if not drafts:
        raise ApiError(f"{flake} has no draft version to edit")
    return max(drafts, key=lambda v: int(v["id"]))["attributes"]["fqn"]


def module_target(module) -> str:
    # Module names look like "@darwinConfiguration@host" or "@homeManagerModule@name".
    parts = module["attributes"]["name"].split("@")
    return parts[2] if len(parts) > 2 else module["attributes"]["name"]


def find_setting(version_doc, option: str, target: Optional[str]):
    """The one setting named `option` (for `target`, when given), with its target."""
    included = version_doc.get("included", [])
    modules = {m["id"]: m for m in included if m["type"] == "nixos_modules"}

    def target_of(setting):
        module = modules.get(setting["relationships"]["module"]["data"]["id"])
        return module_target(module) if module else "?"

    hits = [
        (s, target_of(s))
        for s in included
        if s["type"] == "nixos_settings" and s["attributes"]["name"] == option
    ]
    hits = [h for h in hits if target is None or h[1] == target]
    if not hits:
        raise ApiError(f"no setting {option}" + (f" with target {target}" if target else ""))
    if len(hits) > 1:
        targets = ", ".join(t for _, t in hits)
        raise ApiError(f"{option} is set for several targets ({targets}); pick one with --target")
    return hits[0]


def is_expression(value) -> bool:
    return isinstance(value, dict) and value.get("_type") == "literalExpression"


def show_value(value) -> str:
    return value.get("text", "") if is_expression(value) else json.dumps(value, indent=2)


def value_from_text(old, text: str):
    """`text` as a value of the same kind as the setting's current value."""
    if is_expression(old):
        return {"_type": "literalExpression", "text": text}
    if isinstance(old, str):
        return text
    return json.loads(text)


def setting_patch(setting, value):
    rel = setting["relationships"]
    return {
        "data": {
            "type": "nixos_settings",
            "id": setting["id"],
            "attributes": {"name": setting["attributes"]["name"], "value": value},
            "relationships": {
                k: {"data": rel[k]["data"]} for k in ("module", "option", "flakeInput") if k in rel
            },
        }
    }


def is_package_list(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(v, dict) and v.get("_type") == "package_ref" for v in value
    )


def has_package(value, pid: str) -> bool:
    return any(str(v["package"]["id"]) == pid for v in value)


def with_package(value, pid: str):
    return value + [{"_type": "package_ref", "flake_input": {"name": "__resolve__"}, "package": {"id": pid}}]


def package_id_from_page(html: str, name: str, package_flake: str) -> str:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    obj = json.loads(m.group(1))["props"]["pageProps"].get("object") if m else None
    if not obj or obj.get("type") != "package":
        raise ApiError(f"no package {name} in {package_flake}")
    return str(obj["id"])


def app_bundle_path(page: str) -> str:
    m = re.search(r"/_next/static/chunks/pages/_app-[0-9a-f]+\.js", page)
    if not m:
        raise ApiError("couldn't find the site's _app bundle to read its Firebase key")
    return m.group(0)


def firebase_key_from_bundle(bundle: str) -> str:
    k = re.search(r'"apiKey":"(AIza[0-9A-Za-z_-]+)"', bundle)
    if not k:
        raise ApiError("couldn't find the Firebase API key; set MYNIXOS_FIREBASE_API_KEY")
    return k.group(1)


def error_detail(raw: str) -> str:
    """The `errors[].detail` of a JSON:API error body, or the `error.message`
    of a Google API one, else the body's start."""
    try:
        doc = json.loads(raw)
        details = "; ".join(x.get("detail", str(x)) for x in doc.get("errors", []))
        return details or doc.get("error", {}).get("message") or raw[:300]
    except (ValueError, AttributeError):
        return raw[:300]


def action_request(version, kind: str, extra_args, now: str):
    attrs = {"created": now, "kind": kind, "state": "INIT", "updated": now}
    return {
        "data": {
            "type": "actions",
            "attributes": {**attrs, "args": extra_args} if extra_args else attrs,
            "relationships": {"targetObject": {"data": {"type": "nix_flake_versions", "id": version["id"]}}},
        },
        "meta": {"requestTimestamp": now},
    }


def server_sent_events(lines: Iterable[str]) -> Iterator[Tuple[Optional[str], object]]:
    """(event, data) for each `data:` line, data parsed as JSON."""
    event = None
    for line in lines:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            yield event, json.loads(line[5:].strip() or "null")


class ActionStep(NamedTuple):
    state: Optional[str]
    log: str
    done: bool


def action_step(state: Optional[str], event: Optional[str], data) -> ActionStep:
    """The action's state after one event, the log text it carries, and
    whether it was the last."""
    if event == "mnos_error":
        raise ApiError(f"action failed: {data}")
    if event == "mnos_action_log":
        return ActionStep(state, data.get("text", ""), False)
    if event == "mnos_action_update":
        return ActionStep(data.get("state", state), "", False)
    return ActionStep(state, "", event == "mnos_signal" and data == "end")


# Effects: the network, processes and files


def http(method: str, url: str, headers, data: Optional[bytes] = None) -> bytes:
    # The site's CDN refuses Python's default User-Agent.
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = error_detail(e.read().decode(errors="replace"))
        raise ApiError(f"{method} {url.split('?')[0]}: HTTP {e.code}: {detail}") from None


def fetch_text(url: str) -> str:
    return http("GET", url, {}).decode()


def token_command_output(command: str) -> str:
    # The command may prompt (an unlock dialog, a GPG passphrase), so its
    # stdin and stderr stay the terminal's; only stdout is the token.
    result = subprocess.run(["sh", "-c", command], stdout=subprocess.PIPE, text=True)
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise ApiError(f"MYNIXOS_TOKEN_COMMAND exited {result.returncode} without a token")
    return token


def exchange_refresh_token(refresh: str, api_key: str) -> str:
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
    try:
        raw = http("POST", "https://securetoken.googleapis.com/v1/token?key=" + api_key, {}, body)
    except ApiError as e:
        raise ApiError(f"{e}; sign in on mynixos.com again and copy a fresh refresh token") from None
    return json.loads(raw)["id_token"]


def token_source(cfg: Config) -> Callable[[bool], Optional[str]]:
    """A function returning the ID token, or None when there is no
    credential. Given False it never runs the token command, so reads that
    don't need a token never trigger its prompt. Each token is fetched at
    most once per run."""

    @functools.lru_cache(maxsize=None)
    def exchanged(refresh: str) -> str:
        key = cfg.firebase_api_key or firebase_key_from_bundle(fetch_text(WEB + app_bundle_path(fetch_text(WEB + "/"))))
        return exchange_refresh_token(refresh, key)

    @functools.lru_cache(maxsize=None)
    def command_token() -> str:
        return token_command_output(cfg.token_command)

    def token(interactive: bool) -> Optional[str]:
        if cfg.id_token:
            return cfg.id_token
        refresh = cfg.refresh_token or (command_token() if interactive and cfg.token_command else None)
        return exchanged(refresh) if refresh else None

    return token


class Client(NamedTuple):
    fqn: str
    token: Callable[[bool], Optional[str]]


def request(client: Client, method: str, path: str, body=None, auth_required: bool = False):
    token = client.token(auth_required)
    if auth_required and not token:
        raise ApiError("set MYNIXOS_ID_TOKEN, MYNIXOS_REFRESH_TOKEN or MYNIXOS_TOKEN_COMMAND for this command")
    headers = {
        "Accept": JSON_API,
        **({"Authorization": "JWT " + token} if token else {}),
        **({"Content-Type": JSON_API} if body is not None else {}),
    }
    raw = http(method, API + path, headers, json.dumps(body).encode() if body is not None else None)
    return json.loads(raw) if raw else None


def draft_version(client: Client):
    """The flake's draft version, with its settings included."""
    fqn = latest_draft_fqn(request(client, "GET", client.fqn + "?include=versions"), client.fqn)
    return request(client, "GET", fqn + VERSION_INCLUDE)


def save_setting(client: Client, setting, value):
    """Save `value` to `setting` and return the value read back."""
    path = f"/nixos_settings/{setting['id']}{SETTING_INCLUDE}"
    request(client, "PATCH", path, setting_patch(setting, value), auth_required=True)
    return request(client, "GET", path)["data"]["attributes"]["value"]


def start_action(client: Client, kind: str, extra_args=None) -> str:
    version = draft_version(client)["data"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    body = action_request(version, kind, extra_args, now)
    action = request(client, "POST", version["attributes"]["fqn"] + "/action", body, auth_required=True)
    return action["data"]["attributes"].get("taskId")


def follow_action(task_id: str) -> Optional[str]:
    """Stream the action's log to stderr until it ends; return its final state."""
    req = urllib.request.Request(
        f"{API}/action-response?task_id={task_id}",
        headers={"Accept": "text/event-stream", "User-Agent": USER_AGENT},
    )
    state = None
    with urllib.request.urlopen(req) as resp:
        lines = (raw.decode(errors="replace").rstrip("\n") for raw in resp)
        for event, data in server_sent_events(lines):
            state, log, done = action_step(state, event, data)
            sys.stderr.write(log)
            if done:
                break
    return state


# Commands: each returns its output


def cmd_setting_get(client: Client, args) -> str:
    setting, target = find_setting(draft_version(client), args.option, args.target)
    return f"# setting {setting['id']}, target {target}\n{show_value(setting['attributes']['value'])}"


def cmd_setting_set(client: Client, args) -> str:
    setting, target = find_setting(draft_version(client), args.option, args.target)
    with open(args.file) as f:
        new = value_from_text(setting["attributes"]["value"], f.read())
    if save_setting(client, setting, new) != new:
        raise ApiError(f"saved {args.option}, but reading it back gives a different value")
    return f"saved {args.option} for target {target} (setting {setting['id']}); read back and matched"


def cmd_package_add(client: Client, args) -> str:
    setting, target = find_setting(draft_version(client), args.option, args.target)
    value = setting["attributes"]["value"]
    if not is_package_list(value):
        raise ApiError(f"{args.option} isn't a package-list setting")
    page = fetch_text(f"{WEB}/{args.package_flake}/package/{urllib.parse.quote(args.package)}")
    pid = package_id_from_page(page, args.package, args.package_flake)
    if has_package(value, pid):
        return f"{args.package} is already in {args.option}"
    if not has_package(save_setting(client, setting, with_package(value, pid)), pid):
        raise ApiError(f"saved {args.option}, but {args.package} isn't in it when read back")
    return f"added {args.package} (package {pid}) to {args.option} for target {target}"


def cmd_input_update(client: Client, args) -> str:
    state = follow_action(start_action(client, "LOCK", {"updateInputs": [args.name]}))
    return f"input {args.name}: lock update {state or 'finished'}"


def cmd_release(client: Client, args) -> str:
    task = start_action(client, "RELEASE")
    if not args.wait:
        return f"release started, task {task}"
    state = follow_action(task)
    if state not in (None, "COMPLETE"):
        raise ApiError(f"release ended in state {state}")
    out = subprocess.run(
        ["nix", "flake", "prefetch", "--refresh", "--json", f"{API}{client.fqn}/archive/main.tar.gz"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.stdout)["storePath"]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--flake", help="OWNER/FLAKE; defaults to MYNIXOS_FLAKE")
    p.add_argument(
        "--token-command",
        help="shell command printing a refresh token; defaults to MYNIXOS_TOKEN_COMMAND",
    )
    sub = p.add_subparsers(dest="group", required=True)

    setting = sub.add_parser("setting").add_subparsers(dest="cmd", required=True)
    g = setting.add_parser("get")
    g.add_argument("option")
    g.add_argument("--target")
    g.set_defaults(func=cmd_setting_get)
    s = setting.add_parser("set")
    s.add_argument("option")
    s.add_argument("--file", required=True)
    s.add_argument("--target")
    s.set_defaults(func=cmd_setting_set)

    package = sub.add_parser("package").add_subparsers(dest="cmd", required=True)
    a = package.add_parser("add")
    a.add_argument("option")
    a.add_argument("package")
    a.add_argument("--target")
    a.add_argument("--package-flake", default="nixpkgs")
    a.set_defaults(func=cmd_package_add)

    inp = sub.add_parser("input").add_subparsers(dest="cmd", required=True)
    u = inp.add_parser("update")
    u.add_argument("name")
    u.set_defaults(func=cmd_input_update)

    r = sub.add_parser("release")
    r.add_argument("--wait", action="store_true")
    r.set_defaults(func=cmd_release)
    return p


def main():
    args = parser().parse_args()
    cfg = config_from(os.environ, args)
    try:
        print(args.func(Client(flake_fqn(cfg.flake), token_source(cfg)), args))
    except ApiError as e:
        sys.exit(f"mynixos: {e}")


if __name__ == "__main__":
    main()
