#!/usr/bin/env python3
"""Verify the checked-in lightweight clients cover the preferred operations."""

from pathlib import Path
import sys

REQUIRED = {
    "getAwardAssetContent",
    "putAwardAssetContent",
    "createAwardPreview",
    "patchProgramme",
    "assignProgrammeEntityCategory",
    "unassignProgrammeEntityCategory",
    "patchProgrammeContent",
    "patchProgrammePolicyDraft",
    "patchIdentityAccount",
    "patchIdentityProfile",
    "getIdentityProfileImage",
    "putIdentityProfileImage",
    "deleteIdentityProfileImage",
    "getAccountProfileImage",
    "patchIdentityRole",
    "createIdentityRole",
    "patchGeodataEntityMetadata",
    "postGeodataEntityLocationEnrichmentRequest",
    "putGeodataEntityGeometry",
    "putGeodataEntityCategories",
    "postGeodataEntityReview",
    "postGeodataProposal",
    "createGeodataEntityDeletionJob",
    "confirmGeodataEntityDeletionJob",
    "patchAward",
}

ROOT = Path(__file__).resolve().parents[1]
targets = [
    ROOT / "typescript/myotaClient.ts",
    ROOT / "python/myota_client.py",
]
names = {
    targets[0]: REQUIRED,
    targets[1]: {
        "get_award_asset_content",
        "put_award_asset_content",
        "create_award_preview",
        "patch_programme",
        "assign_programme_entity_category",
        "unassign_programme_entity_category",
        "patch_programme_content",
        "patch_programme_policy_draft",
        "patch_identity_account",
        "patch_identity_profile",
        "get_identity_profile_image",
        "put_identity_profile_image",
        "delete_identity_profile_image",
        "get_account_profile_image",
        "patch_identity_role",
        "create_identity_role",
        "patch_geodata_entity_metadata",
        "post_geodata_entity_location_enrichment_request",
        "put_geodata_entity_geometry",
        "put_geodata_entity_categories",
        "post_geodata_entity_review",
        "post_geodata_proposal",
        "create_geodata_entity_deletion_job",
        "confirm_geodata_entity_deletion_job",
        "patch_award",
    },
}
missing = []
for target in targets:
    content = target.read_text(encoding="utf-8")
    missing.extend(
        f"{target}: {name}" for name in names[target] if name not in content
    )
if missing:
    print("Generated client coverage is incomplete:\n" + "\n".join(missing))
    sys.exit(1)
print(
    f"checked {len(targets)} clients and {len(REQUIRED)} preferred operations"
)
