# aws-intel

`aws-intel` is a command-line tool for retrieving useful information from AWS.

The project is in its initial development stage.

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
```

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
