# aws-intel

`aws-intel` is a command-line tool for retrieving useful information from AWS.

The project is in its initial development stage.

Every invocation checks PyPI for a newer release. When an update is available,
`awsi` writes a short upgrade notice to standard error so command output on
standard output remains safe to pipe or parse. The check has a one-second
timeout and is silently skipped when PyPI cannot be reached.

## Requirements

- Python 3.10 or newer
- [Poetry](https://python-poetry.org/)

## Development

Install the project and its development dependencies:

```shell
poetry install
```

Run the CLI:

```shell
poetry run awsi --help
```

Commands follow this structure:

```text
awsi <utility> <options>
```

List all available utilities and their descriptions, or show detailed help for
one utility:

```shell
awsi help
awsi help security-group-tree
awsi help forward
awsi help login
awsi help console
awsi help shell-init
```

Open a shell authenticated to an account defined in `.awsi/accounts.yaml`:

```shell
awsi login example-development
aws sts get-caller-identity
exit
```

List the accounts available in the current configuration without logging in:

```shell
awsi login --list
```

When an account defines a temporary TEAM role, request access through TEAM and
open an elevated shell after the request becomes active:

```shell
awsi login example-development --elevated
```

When run without an account name in an interactive terminal, `awsi login`
shows the configured accounts and asks which one to use. If the selected
account defines TEAM elevated access, it also asks which access level to use:

```text
$ awsi login
Select an AWS account:
  1. example-hub
  2. example-development
Account [1-2]: 2
Select access role:
  1. standard-access (standard access)
  2. elevated-access (TEAM elevated)
Access [1-2]: 2
```

Press Escape, Ctrl+C, or Ctrl+D to cancel either interactive selection.

After authentication, `awsi` reports the exact expiration returned by AWS and
the time remaining before it opens the authenticated shell. It also prefixes
the shell prompt with the active account name.

From inside that authenticated shell, open the AWS Management Console with the
same account and role in the default browser:

```shell
awsi console
```

The temporary console sign-in URL is opened directly and is never printed.

If a zsh theme replaces the prompt supplied by `awsi login`, add this line to
`~/.zshrc` so the account label is applied after the theme loads:

```zsh
eval "$(awsi shell-init zsh)"
```

For example, an authenticated prompt will start with:

```text
[example-development] user@host project %
```

The normal prompt is unchanged outside an `awsi login` shell.

The root account contains its IAM Identity Center details. An account with a
`source` first obtains credentials for that source and then assumes its own
configured role:

```yaml
version: 1

accounts:
  example-hub:
    account_id: "111111111111"
    role_name: standard-access
    sso_start_url: https://example.awsapps.com/start
    sso_region: eu-west-1
    region: eu-west-1

  example-development:
    account_id: "222222222222"
    role_name: standard-access
    source: example-hub
    region: eu-central-1
    elevated_access:
      provider: team
      role_name: elevated-access
```

Normal login continues to use the configured read-only role chain. Elevated
login uses the TEAM role as a direct IAM Identity Center assignment. If the
assignment is not active, `awsi` tells the user to request TEAM access and
retry.

`awsi` supplies a temporary AWS CLI configuration only while completing the
SSO login, so an existing `~/.aws/config` is not required or modified. The
authenticated subshell receives temporary credentials through environment
variables. They disappear when the shell exits; no credentials are written to
the repository or to `~/.aws/credentials`.

For example:

```shell
awsi security-group-tree sg-0123456789abcdef0
```

`security-group-tree` recursively displays security groups, their attached
resources, IPv4 and IPv6 ranges, and managed prefix lists connected through
inbound and outbound rules. Each connection is prefixed with its protocol and
port or port range and its direction, such as `tcp 443 from 10.0.0.0/8` for an
inbound rule or `udp 1000-2000 to 10.0.0.0/8` for an outbound rule. Attached
resources are grouped under `Assigned to`, inbound connections under `Sources`,
and outbound connections under `Targets`. Resource discovery includes
AWS-managed network interfaces. Resource `Name` tags are displayed when
available, with existing descriptions or IDs used as fallbacks. This requires
permission to call `ec2:DescribeNetworkInterfaces` and `ec2:DescribeTags`.
Referenced security groups are displayed as `sg-0123456789abcdef0 (name)` so
the rule's actual source or target identifier appears before its descriptive
name.

For RFC 1918 IPv4 ranges, the command also lists network interfaces in the
security group's VPC whose primary or secondary private address is within the
range. Each match includes its concrete private IP address. Public IPv4 and
IPv6 ranges are not resolved, and resources in other accounts, Regions, peered
VPCs, transit networks, or on-premises networks are outside the lookup scope.

The command uses the active AWS CLI credentials and region. Limit output to one
direction with `--inbound` or `--outbound`; the flags are mutually exclusive.
Filter the displayed tree with `--filter TEXT`. Matching is case-insensitive;
matching nodes retain their descendants, and ancestor paths are retained for
context. The `Assigned to` metadata for security groups on a matching path is
also retained. For example, `--filter acc` finds labels containing `ACC`.
Control recursive security-group expansion with `--depth DEPTH`. The default
depth is 1, which shows resources and rules inside the starting security group
without expanding the contents of referenced groups. The maximum is 3 because
each expanded group and private network can require additional AWS API calls,
and the number of referenced groups can grow rapidly at each level.
Interactive terminals show a loading indicator while AWS resources are being
retrieved. The indicator is written to standard error and is disabled when
output is redirected or piped.

Start an SSM port forwarding session through an online, SSM-managed EC2
instance to a host reachable from that instance:

```shell
awsi forward start primary-database \
  --instance-id=i-0123456789abcdef0 \
  --host=db.internal --port=5432:5432
```

The bastion can also be selected by its exact EC2 `Name` tag, which remains
stable when an instance is replaced:

```shell
awsi forward start database --instance-name=public-bastion \
  --host=db.internal --port=5432:5432
```

Only active (`pending` or `running`) instances are considered. The command
fails rather than choosing arbitrarily if multiple active instances have the
same `Name` tag. `--instance-id` and `--instance-name` are mutually exclusive.

The first port is the local listening port and the second is the remote host's
port. The command uses the
`AWS-StartPortForwardingSessionToRemoteHost` document and starts the session in
the background, then prints a confirmation containing the process ID. The AWS
CLI and its Session Manager plugin must be installed.

Before starting, `awsi` rejects an identical forward that is already active
and verifies that the requested local port is available. The command exits
with an error instead of launching another session when either check fails.

Save a named forward without resolving the instance or starting a session:

```shell
awsi forward save apigateway-dev \
  --instance-name=solo-connect-bastion-dev \
  --host=internal-apigw-internal-dev-2025348469.eu-west-1.elb.amazonaws.com \
  --port=9072:9072
```

The `save` action adds or replaces that name in `.awsi/forwards.yaml` under
the current working directory without resolving the instance or starting a
session. The generated configuration looks like this:

```yaml
forwards:
  apigateway-dev:
    instance-name: solo-connect-bastion-dev
    host: internal-apigw-internal-dev-2025348469.eu-west-1.elb.amazonaws.com
    port: 9072:9072
```

Start a saved forward by its configuration name:

```shell
awsi forward start apigateway-dev
```

The command reads `.awsi/forwards.yaml` from the current working directory,
resolves the configured instance when necessary, and starts the forward using
the saved host and port mapping.

When run without a name or connection options in an interactive terminal,
`awsi forward start` shows the saved forwards from `.awsi/forwards.yaml` and
starts the selected one:

```text
$ awsi forward start
Select a forward:
  1. apigateway-dev
  2. primary-database
Forward 'apigateway-dev' started in the background with PID 4321.
```

Press Escape, Ctrl+C, or Ctrl+D to cancel the interactive selection.

List all saved definitions with:

```shell
awsi forward list
```

List forwards started by `awsi` that still have a running process with:

```shell
awsi forward active
```

The output has a tab-separated header and columns for process ID, optional name
(`-` when unnamed), bastion instance ID, remote host, and the port mapping.
Completed forwards are removed from the list:

```text
PID	NAME	INSTANCE_ID	HOST	PORT
4321	primary-database	i-0123456789abcdef0	db.internal	5432:5432
```

End an active forward by its exact name:

```shell
awsi forward stop primary-database
```

If no forward has that name, the reference is interpreted as a process ID:

```shell
awsi forward stop 40234
```

Stop every active forward with:

```console
awsi forward stop --all
```

When run without a name, PID, or `--all` in an interactive terminal,
`awsi forward stop` shows only the active forwards and stops the selected
one:

```text
$ awsi forward stop
Select a forward:
  1. primary-database (PID 4321)
  2. PID 4322
Forward 'primary-database' with PID 4321 was terminated.
```

Press Escape, Ctrl+C, or Ctrl+D to cancel the interactive selection.

Restart an active forward by name or PID, preserving its current connection
details, or restart every active forward:

```console
awsi forward restart primary-database
awsi forward restart --all
```

Only forwards tracked by `awsi` can be terminated. When multiple active
forwards share a name, use the process ID shown by `--list`.
List online SSM-managed EC2 instances in the active account and region with:

```shell
awsi forward hosts
```

The list is tab-separated: instance ID followed by the EC2 `Name` tag when one
is present. Listing requires `ssm:DescribeInstanceInformation` and
`ec2:DescribeInstances`; starting a session requires the corresponding
`ssm:StartSession` and session-channel permissions.

`awsi forward NAME`, `awsi forward --list`, `awsi forward --kill`, and
`awsi forward --list-hosts` remain available as
compatibility aliases, but the action-based forms above are the recommended
interface. Forward names are positional; the former `--name` option is no
longer supported.

Supply multiple security group IDs to combine them as sibling roots in one
tree:

```shell
awsi security-group-tree sg-0123456789abcdef0 sg-11111111111111111
```

Run the tests:

```shell
poetry run pytest
```

Build distribution artifacts:

```shell
poetry build
```

## Continuous integration and releases

Pull requests and pushes to `main` run the test suite on the oldest and newest
supported Python versions. After the tests pass, CI builds the wheel and source
distribution and stores them as workflow artifacts.

Releases use the **Publish to PyPI** workflow:

1. In the repository's **Actions** tab, select **Publish to PyPI** and choose
   **Run workflow** from the `main` branch.
2. Choose `patch`, `minor`, or `major` for the semantic version increment.
3. Approve the `pypi` environment deployment when prompted.

Before the first release:

- Add the appropriate project authors and license metadata to `pyproject.toml`
  and confirm that the `aws-intel` name is available on PyPI.
- Create a GitHub Environment named `pypi` and add the required reviewers whose
  approval is needed to publish.
- Configure a PyPI trusted publisher for this repository, the `publish.yml`
  workflow, and the `pypi` environment. No PyPI API token is required.
- Ensure repository rules allow GitHub Actions to push the release version
  commit to `main`.

After approval, the workflow reruns the tests, increments the version in
`pyproject.toml`, builds the distributions, pushes the version commit to
`main`, and publishes through PyPI trusted publishing. Only one release
workflow can run at a time.
