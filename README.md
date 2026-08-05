# AWS Intel

AWS Intel (`awsi`) is a command-line utility for signing in to AWS accounts,
inspecting security-group relationships, opening the AWS Management Console,
and managing SSM port-forwarding sessions.

## Requirements

- Python 3.10 or newer
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

## Installation

Install the latest release with [pipx](https://pipx.pypa.io/), which keeps the
application in an isolated environment while making `awsi` available on your
`PATH`:

```shell
pipx install aws-intel
```

Alternatively, install it into the current Python environment:

```shell
python -m pip install aws-intel
```

Verify the installation:

```shell
awsi --version
awsi help
```

Every invocation performs a one-second PyPI version check. If a newer release
is available, the upgrade notice is written to standard error; command output
on standard output remains safe to pipe or parse. An unavailable PyPI endpoint
does not prevent the command from running.

## Quick start

Create example configuration files in the current directory:

```shell
awsi init
```

This creates `.awsi/accounts.yaml` and `.awsi/forwards.yaml`. Existing files
are preserved. To replace both files with fresh examples, use:

```shell
awsi init --force
```

Edit the generated values, then sign in and verify the active identity:

```shell
awsi login example-chained
aws sts get-caller-identity
exit
```

Configuration is resolved relative to the current working directory. Run
`awsi` from the directory containing `.awsi`.

## Configuration

### AWS accounts

`.awsi/accounts.yaml` defines the accounts available to `awsi login`. A root
account authenticates directly with IAM Identity Center. A chained account
names another account as its `source`; AWS Intel signs in through the root and
assumes each configured role in order.

#### Complete `accounts.yaml` example

The two definitions below collectively demonstrate every supported option.
Replace all example values with values for your AWS environment.

```yaml
version: 1

accounts:
  example-source:
    account_id: "111111111111"
    role_name: ExampleSourceRole
    region: eu-west-1
    color: "#4F8EF7"
    sso_start_url: https://example.awsapps.com/start
    sso_region: eu-west-1
    elevated_access:
      provider: team
      role_name: ExampleSourceElevatedRole

  example-chained:
    account_id: "222222222222"
    role_name: ExampleChainedRole
    region: eu-central-1
    color: "#F59E0B"
    source: example-source
    session_duration_hours: 4
    elevated_access:
      provider: team
      role_name: ExampleChainedElevatedRole
      source_role: ExampleSourceElevatedRole
```

#### Account options

| Option | Required | Description |
| --- | --- | --- |
| `version` | Yes | Configuration schema version. The only supported value is `1`. |
| `accounts` | Yes | Mapping of user-defined account names to account definitions. Names are used by `awsi login`. |
| `account_id` | Yes | The 12-digit AWS account ID. Quote it so YAML treats it as a string. |
| `role_name` | Yes | IAM role used for standard access to this account. |
| `region` | No | AWS Region used after login and while assuming this account's role. Defaults to `eu-west-1`. |
| `color` | No | Color of the authenticated shell label. Use a CSS basic color name or a quoted `#RRGGBB` hex value. Requires a terminal with true-color support. |
| `source` | Chained accounts only | Name of another entry in `accounts` through which this role is assumed. Chains may contain multiple accounts but may not contain cycles. |
| `sso_start_url` | Root accounts only | IAM Identity Center access-portal URL. Required on the root of a login chain and invalid when `source` is set. |
| `sso_region` | Root accounts only | Region containing the IAM Identity Center configuration. Required on the root of a login chain and invalid when `source` is set. |
| `session_duration_hours` | No | Requested role-session duration for a chained account, as an integer from `1` through `12`. Invalid on a root account. The role's configured maximum duration still applies. |
| `elevated_access` | No | TEAM elevated-access settings for this account. |
| `elevated_access.provider` | With `elevated_access` | Elevated-access provider. The only supported value is `team`. |
| `elevated_access.role_name` | With `elevated_access` | Elevated role used in the target account. |
| `elevated_access.source_role` | No | Role to use for every source-account hop during elevated login. If omitted, source accounts retain their normal `role_name`. |

The root account must contain `sso_start_url` and `sso_region`. Other accounts
in the chain must use `source` instead. Temporary credentials are placed only
in the authenticated subshell environment; AWS Intel does not modify
`~/.aws/config` or write credentials to the repository or
`~/.aws/credentials`.

The supported CSS basic color names are `black`, `silver`, `gray`, `white`,
`maroon`, `red`, `purple`, `fuchsia`, `green`, `lime`, `olive`, `yellow`,
`navy`, `blue`, `teal`, and `aqua`. Names are case-insensitive. Custom colors
must be quoted so YAML does not interpret the leading `#` as a comment:

```yaml
color: red
# or use a custom RGB value:
# color: "#123123"
```

### Saved port forwards

`.awsi/forwards.yaml` defines reusable SSM port-forwarding connections. Each
forward selects its bastion by either EC2 instance ID or exact EC2 `Name` tag.

#### Complete `forwards.yaml` example

The alternatives `instance-id` and `instance-name` cannot appear in the same
forward, so this example includes one definition of each kind.

```yaml
forwards:
  database-by-id:
    instance-id: i-0123456789abcdef0
    host: database.internal.example
    port: 5432:5432

  api-by-name:
    instance-name: public-bastion
    host: api.internal.example
    port: 8080:80
```

#### Forward options

| Option | Required | Description |
| --- | --- | --- |
| `forwards` | No | Mapping of user-defined forward names to definitions. An omitted or empty mapping means no saved forwards. |
| `instance-id` | Exactly one selector | EC2 instance ID of the online, SSM-managed bastion. Mutually exclusive with `instance-name`. |
| `instance-name` | Exactly one selector | Exact EC2 `Name` tag of the online, SSM-managed bastion. The command fails if multiple active instances have that name. Mutually exclusive with `instance-id`. |
| `host` | Yes | Hostname or IP address reachable from the bastion. |
| `port` | Yes | TCP mapping in `LOCAL_PORT:REMOTE_PORT` format. Both ports must be integers from `1` through `65535`. |

Only EC2 instances in `pending` or `running` state are considered when
resolving `instance-name`. `awsi forward save` can add or replace a definition
without starting it.

## Command-line usage

Commands use this structure:

```text
awsi <utility> <options>
```

Discover utilities and their current options with:

```shell
awsi help
awsi help login
awsi help forward
awsi <utility> --help
```

### Log in to an AWS account

```shell
awsi login [ACCOUNT]
awsi login --list
awsi login ACCOUNT --elevated
```

`awsi login` performs IAM Identity Center authentication, resolves the account
chain, and opens a subshell containing temporary credentials. Exit that shell
to return to the previous session. With no account in an interactive terminal,
it prompts for a configured account and, when available, standard or TEAM
elevated access. Escape, Ctrl+C, and Ctrl+D cancel a selection.

`--list` prints configured account names without logging in. `--elevated` uses
the account's configured temporary TEAM role; the TEAM assignment must already
be active.

### Open the AWS Management Console

From a shell opened by `awsi login`, run:

```shell
awsi console
```

AWS Intel exchanges the current temporary credentials for a console sign-in
URL and opens it in the default browser. The URL is never printed.

### Label authenticated zsh sessions

If a zsh theme replaces the prompt set by `awsi login`, add this to `~/.zshrc`:

```zsh
eval "$(awsi shell-init zsh)"
```

Authenticated prompts are prefixed with the active role and account, such as
`[ExampleSourceRole@example-source]`. Prompts outside an AWS Intel login shell
are unchanged.

### Inspect a security group tree

```shell
awsi security-group-tree SECURITY_GROUP_ID [SECURITY_GROUP_ID ...] [options]
```

Examples:

```shell
awsi security-group-tree sg-0123456789abcdef0
awsi security-group-tree sg-0123456789abcdef0 --depth 2 --inbound
awsi security-group-tree sg-0123456789abcdef0 --filter database
```

Options:

| Option | Description |
| --- | --- |
| `--depth DEPTH` | Expand referenced security groups to a depth from `1` to `3`. Default: `1`. |
| `--filter TEXT` | Case-insensitively retain matching nodes, their descendants, and their ancestor paths. |
| `--inbound` | Show only inbound connections. Mutually exclusive with `--outbound`. |
| `--outbound` | Show only outbound connections. Mutually exclusive with `--inbound`. |

The command uses the active AWS CLI credentials and Region. It displays
attached resources, IPv4 and IPv6 ranges, managed prefix lists, and connected
security groups. For RFC 1918 IPv4 ranges, it also resolves matching network
interfaces inside the security group's VPC. This discovery requires
`ec2:DescribeNetworkInterfaces` and `ec2:DescribeTags` in addition to
permission to describe security groups and prefix lists.

### Manage SSM port forwards

Start a saved forward:

```shell
awsi forward start database-by-id
```

Start an explicitly described forward without saving it:

```shell
awsi forward start database \
  --instance-name public-bastion \
  --host database.internal.example \
  --port 5432:5432
```

Save or replace a definition without starting it:

```shell
awsi forward save database \
  --instance-id i-0123456789abcdef0 \
  --host database.internal.example \
  --port 5432:5432
```

List and manage forwards:

```shell
awsi forward list
awsi forward hosts
awsi forward active
awsi forward stop database
awsi forward stop 4321
awsi forward stop --all
awsi forward restart database
awsi forward restart 4321
awsi forward restart --all
```

Running `awsi forward start` without arguments interactively selects one or
more saved definitions. Saved forwards that are already running remain visible
in the selection overview as active, but cannot be selected again. Running
`awsi forward stop` without a name, PID, or `--all` interactively selects
active sessions. Active-session output is
tab-separated and includes a header. AWS Intel rejects duplicate active
forwards and unavailable local ports before starting a background session.

`awsi forward hosts` requires `ssm:DescribeInstanceInformation` and
`ec2:DescribeInstances`. Starting a session requires `ssm:StartSession` and
the associated session-channel permissions.

The legacy forms `awsi forward NAME`, `awsi forward --list`,
`awsi forward --kill`, and `awsi forward --list-hosts` remain supported for
backward compatibility. The action-based commands above are recommended.

### Generate configuration

```shell
awsi init [--force]
```

This writes anonymized examples to `.awsi/accounts.yaml` and
`.awsi/forwards.yaml` in the current directory. `--force` overwrites existing
configuration files. The complete examples in the configuration section above
show every supported field, including mutually exclusive alternatives.

## Contributing

The project uses [Poetry](https://python-poetry.org/) for development. Clone
the repository, then install the package and development dependencies:

```shell
poetry install
```

Run the CLI and test suite:

```shell
poetry run awsi --help
poetry run pytest
```

Build wheel and source-distribution artifacts with:

```shell
poetry build
```

Keep CLI parsing and presentation separate from application logic, isolate AWS
CLI calls behind integration boundaries, and add deterministic tests for
behavior changes. Tests must not contact live AWS services unless explicitly
marked as integration tests.
