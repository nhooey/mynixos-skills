---
name: mynixos-api
description: Read and change a MyNixOS flake (mynixos.com) through its HTTP API at api.mynixos.com instead of the website, with the bundled standard-library Python client scripts/mynixos.py. Covers reading a setting, saving a setting's value, adding a package to a package-list setting, updating a flake input's lock and publishing a release, plus the API's resources, request shapes and authentication. Use it when a MyNixOS change can be scripted, when the browser isn't available, or when the API itself comes up. The API is undocumented, so fall back to mynixos-v1-browser-config-change whenever a call fails.
---

# Change a MyNixOS flake through its API

The website at mynixos.com is a front end over a JSON:API service at
`https://api.mynixos.com`. Everything the website does is an API call, so a
setting can be read, saved and released from a script. The API is not
documented or promised: the shapes below were read from the website's own
JavaScript and can change with any site update.

**When a call fails, stop and make the change in the browser** with
`mynixos-v1-browser-config-change`. Don't guess at a new request shape.

## The client

`scripts/mynixos.py` uses only the Python 3 standard library. Run it as
`python3 -I <skill-dir>/scripts/mynixos.py`, with the flake given as
`--flake <owner>/<flake>` or in `MYNIXOS_FLAKE`.

| Command                                      | Does                                                                                              | Needs a token |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------- |
| `setting get <option> [--target T]`          | prints the setting's id, its target and its value                                                 | no¹           |
| `setting set <option> --file F [--target T]` | saves the file's content as the value, then reads it back and compares                            | yes           |
| `package add <option> <pkg> [--target T]`    | adds a package to a package-list setting such as `home.packages`, then checks it's there          | yes           |
| `input update <name>`                        | updates one input's lock, as **Update** does on the Inputs page, and waits for it                 | yes           |
| `release [--wait]`                           | publishes a release; with `--wait`, follows it to the end and prints the new tarball's store path | yes           |

¹ Only for a public flake; a private one needs a token for reads too.

- **`--target`** picks the configuration when the same option is set for more
  than one, such as a host and a Home Manager user. The client refuses to guess.
- **`setting set`** keeps the setting's kind: a Nix expression setting gets
  the file's text as its expression, a plain string setting the text itself,
  and any other kind (boolean, number, list) reads the file as JSON.
- **`package add`** finds the package's id on its page,
  `https://mynixos.com/<flake>/package/<name>`; `--package-flake` names that
  flake, `nixpkgs` by default.
- Every command exits non-zero with a one-line reason on any non-2xx
  response, and never prints a token.

After a change, release, build and verify exactly as
`mynixos-v1-browser-config-change` says; the API only replaces the editing.

## Authentication

Reads of a public flake need nothing. Writes send the signed-in user's
Firebase ID token as `Authorization: JWT <id-token>`. The client takes it
from the environment, in this order:

- **`MYNIXOS_ID_TOKEN`:** an ID token, valid for about an hour. Copy it from
  the website: browser developer tools, Network tab, any request to
  `api.mynixos.com`, the `Authorization` header after `JWT `.
- **`MYNIXOS_REFRESH_TOKEN`:** a long-lived refresh token, which the client
  exchanges for an ID token at `securetoken.googleapis.com`. Copy it from the
  website: developer tools, Application tab, IndexedDB,
  `firebaseLocalStorageDb`, `firebaseLocalStorage`, the entry's
  `value.stsTokenManager.refreshToken`. The exchange needs the site's public
  Firebase web API key, which the client reads from the site's `_app` bundle,
  or from `MYNIXOS_FIREBASE_API_KEY`.
- **`MYNIXOS_TOKEN_COMMAND`, or `--token-command`:** a shell command that
  prints the refresh token, run only by commands that need a token. It keeps
  the token out of the environment, in a store that can lock itself:
  - macOS, a keychain that locks after idle time:
    `security find-generic-password -s mynixos-refresh-token -w ~/Library/Keychains/<keychain>.keychain-db`
  - Linux, `pass`, whose gpg-agent forgets the passphrase after
    `default-cache-ttl`: `pass show mynixos/refresh-token`

  When the store is locked, the command's own prompt (an unlock dialog, a
  passphrase) appears, so a write can wait on the user.

All of these are credentials for the account: keep them in a locking store
or a secrets file the shell reads, never in a setting, a repository or a
command line the agent echoes. The agent never reads, prints or stores their
values; it asks the user to put them in place.

## The API

All resources are JSON:API (`application/vnd.api+json`): an object has
`type`, `id`, `attributes` and `relationships`, and `?include=` pulls related
objects into `included`.

### Reading

| Request                                                       | Returns                                                                                    |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `GET /<owner>/<flake>?include=versions`                       | the flake, with every version; `attributes.isMutable` marks the draft                      |
| `GET /<owner>/<flake>/version/<id>?include=…`                 | one version, with its modules, settings, options, packages and inputs (include list below) |
| `GET /nixos_settings/<id>?include=option,packageRefs.package` | one setting                                                                                |
| `GET /action-response?task_id=<task>`                         | an action's progress, as server-sent events                                                |

The version include list the website uses:
`inputs.targetFlakeRef.flakeVersion,nixosModules.imports.flakeInput,nixosModules.imports.targetModule,nixosModules.settings.option,nixosModules.settings.packageRefs.package`.

- **Edits go to the draft.** The flake has one mutable version, named
  "Draft", with no release number. A release freezes it and creates a new
  draft, and every setting in the new draft gets a **new id**, so look a
  setting up by its option name in the current draft each time; never keep
  an id across a release.
- **Modules and targets:** each setting belongs to a `nixos_modules` object
  whose name is `@<kind>@<target>`, such as `@darwinConfiguration@<host>` or
  `@homeManagerConfiguration@<user>`.
- **Setting values** come in these kinds:
  - a Nix expression: `{"_type": "literalExpression", "text": "<nix>"}`;
  - a package list: a list of
    `{"_type": "package_ref", "id": …, "package": {"id": …}, "flake_input": {"id": …}}`;
  - a plain JSON boolean, number, string or list of strings.

### Writing

| Change                      | Request                                                                      |
| --------------------------- | ---------------------------------------------------------------------------- |
| save a setting              | `PATCH /nixos_settings/<id>?include=option,packageRefs.package`              |
| create a setting            | `POST /nixos_settings?include=option,packageRefs.package`                    |
| delete a setting            | `DELETE /nixos_settings/<id>`                                                |
| change an input             | `PATCH /nix_flake_inputs/<id>?include=targetFlakeRef.flakeVersion`           |
| lock update, build, release | `POST /<owner>/<flake>/version/<draft-id>/action`                            |
| cancel an action            | `POST /action-command?task_id=<task>` with `{"command": {"kind": "CANCEL"}}` |

- **Saving a setting:** the body is the setting itself, with the new value:

  ```json
  {"data": {"type": "nixos_settings", "id": "<id>",
            "attributes": {"name": "<option>", "value": <value>},
            "relationships": {"module": {"data": …}, "option": {"data": …},
                              "flakeInput": {"data": …}}}}
  ```

- **Adding a package:** append
  `{"_type": "package_ref", "flake_input": {"name": "__resolve__"}, "package": {"id": "<package-id>"}}`
  to the list and save it; the server resolves the input.
- **Creating a setting:** the body names the module and leaves the option
  and input for the server to resolve, with
  `"option": {"data": {"type": "nixos_options", "attributes": {"name": "__resolve__"}}}`
  and the option's name in `attributes.name`.
- **Actions:** the body is

  ```json
  {"data": {"type": "actions",
            "attributes": {"kind": "<KIND>", "state": "INIT", "created": "<now>", "updated": "<now>",
                           "args": { … }},
            "relationships": {"targetObject": {"data": {"type": "nix_flake_versions", "id": "<draft-id>"}}}},
   "meta": {"requestTimestamp": "<now>"}}
  ```

  `kind` is `RELEASE` (no `args`), `LOCK` with `args.updateInputs` (a list of
  input names), `args.updateAll: true` or `args.recreateLockFile: true`, or
  `BUILD` with `args.buildOutputAttrPath`. The response's
  `data.attributes.taskId` names the action's event stream.

- **The event stream** sends `mnos_action_log` (log text),
  `mnos_action_update` (`state`, `COMPLETE` when done), `mnos_error`, and
  `mnos_signal` with `"end"` last.

### Release tarballs

The newest release is served at
`https://api.mynixos.com/<owner>/<flake>/archive/main.tar.gz`. Its `Link`
header (`rel="immutable"`) names the release's fixed archive in the flake's
git repository on `git.mynixos.com`, which is the URL Nix writes into a lock
file.

## Rules

- Read the setting first, change only what was asked, and read it back after
  saving; the client does both.
- A release, a build and a switch are separate steps with their own
  approval, as `mynixos-v1-browser-config-change` says; saving a setting
  never implies one.
- When any call fails or returns something unexpected, stop and make the
  change in the browser instead.

## Related skills

When one of these applies and it's in your skill listing, load it
without asking. If it isn't in your listing, tell the user which skill is
missing and ask whether to install it from the same collection this skill
came from; don't apply it from memory.

- `mynixos-v1-browser-config-change`: the same changes through the website, plus testing, release checks, building, verifying and switching.
- `coding-agent-scratchpad-scripts`: where one-off request files and checks go, so the scratchpad stays readable.
