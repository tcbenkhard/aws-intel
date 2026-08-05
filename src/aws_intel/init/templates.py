"""Boilerplate documents used to populate .awsi configuration files."""


def boilerplate_accounts_document() -> dict[str, object]:
    """Return an accounts.yaml document with anonymized example accounts.

    Includes one source account and one account chained from it, each with
    every field the account schema supports filled with plausible-looking
    values. sso_start_url/sso_region are only valid on a source account, and
    session_duration_hours is only valid on a chained account, so together
    the two accounts demonstrate every supported field.
    """
    return {
        "version": 1,
        "accounts": {
            "example-source": {
                "account_id": "111111111111",
                "role_name": "ExampleSourceRole",
                "region": "eu-west-1",
                "color": "#4F8EF7",
                "sso_start_url": "https://example.awsapps.com/start",
                "sso_region": "eu-west-1",
                "elevated_access": {
                    "provider": "team",
                    "role_name": "ExampleSourceElevatedRole",
                },
            },
            "example-chained": {
                "account_id": "222222222222",
                "role_name": "ExampleChainedRole",
                "region": "eu-west-1",
                "color": "#F59E0B",
                "source": "example-source",
                "session_duration_hours": 4,
                "elevated_access": {
                    "provider": "team",
                    "role_name": "ExampleChainedElevatedRole",
                    "source_role": "ExampleSourceElevatedRole",
                },
            },
        },
    }


def boilerplate_forwards_document() -> dict[str, object]:
    """Return a forwards.yaml document with one anonymized example forward.

    instance-id and instance-name are mutually exclusive, so the forward
    uses instance-id alongside every other field the forward schema
    supports.
    """
    return {
        "forwards": {
            "example-forward": {
                "instance-id": "i-0123456789abcdef0",
                "host": "internal-api.example.local",
                "port": "8080:80",
            },
        },
    }
