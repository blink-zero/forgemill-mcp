"""Tests for _build_deploy_body — the shared body builder used by both
deploy_vm and preview_deploy, confirming it matches Forgemill's
service.DeployRequest field-for-field (including disk_provisioning, the
vCenter/ESXi-only field that was previously missing from both tools).
"""

from __future__ import annotations

from forgemill_mcp.server import _build_deploy_body


def _minimal(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = dict(
        template_id=1,
        target_id=2,
        vm_name="web-01",
        cpu=2,
        memory_mb=2048,
        disk_gb=None,
        datacenter="",
        cluster="",
        host="",
        datastore="",
        folder="",
        network="",
        ip_address="",
        netmask="",
        gateway="",
        dns=None,
        hostname="",
        domain_name="",
        ssh_public_key="",
        disk_provisioning="",
        action_ids=None,
    )
    args.update(overrides)
    return args


def test_build_deploy_body_omits_unset_optional_fields() -> None:
    body = _build_deploy_body(**_minimal())  # type: ignore[arg-type]
    assert body == {
        "template_id": 1,
        "target_id": 2,
        "vm_name": "web-01",
        "cpu": 2,
        "memory_mb": 2048,
    }


def test_build_deploy_body_includes_disk_provisioning_when_set() -> None:
    body = _build_deploy_body(**_minimal(disk_provisioning="thin"))  # type: ignore[arg-type]
    assert body["disk_provisioning"] == "thin"


def test_build_deploy_body_includes_all_optional_fields_when_set() -> None:
    body = _build_deploy_body(
        **_minimal(
            disk_gb=80,
            datacenter="dc1",
            cluster="cluster1",
            host="esxi1",
            datastore="ds1",
            folder="folder1",
            network="VM Network",
            ip_address="10.0.0.5",
            netmask="255.255.255.0",
            gateway="10.0.0.1",
            dns=["1.1.1.1"],
            hostname="web-01",
            domain_name="example.com",
            ssh_public_key="ssh-ed25519 AAAA...",
            disk_provisioning="thick_eager_zero",
            action_ids=[1, 2],
        )
    )  # type: ignore[arg-type]
    assert body["disk_gb"] == 80
    assert body["datacenter"] == "dc1"
    assert body["disk_provisioning"] == "thick_eager_zero"
    assert body["action_ids"] == [1, 2]
    assert body["dns"] == ["1.1.1.1"]
