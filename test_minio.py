import pytest

from types import SimpleNamespace

from minio import (
    load_config,
    
    create_s3_client,

    bucket_exists,
    create_bucket,
    list_buckets,
    delete_bucket,

    object_exists,
    upload_object,
    list_objects,
    get_object_metadata,
    download_object,
    delete_object,
    fully_delete_object,
    remove_object_retention,
    recover_deleted_object,
    visualize_object_versions
)

@pytest.fixture
def args() -> SimpleNamespace:
    return load_config()

@pytest.fixture
def s3_client(args):
    return create_s3_client(args)

def bucket_force_cleanup(s3_client, bucket):
    response = s3_client.list_object_versions(Bucket=bucket)

    for v in response.get("Versions", []):
        s3_client.delete_object(
            Bucket=bucket,
            Key=v["Key"],
            VersionId=v["VersionId"],
            BypassGovernanceRetention=True
        )

    for m in response.get("DeleteMarkers", []):
        s3_client.delete_object(
            Bucket=bucket,
            Key=m["Key"],
            VersionId=m["VersionId"]
        )

    delete_bucket(s3_client, bucket)

@pytest.fixture
def bucket(s3_client):
    name = f"test-bucket"

    if bucket_exists(s3_client, name):
        bucket_force_cleanup(s3_client, name)

    create_bucket(s3_client, name, object_lock_enabled=True)
    yield name

    # force cleanup
    bucket_force_cleanup(s3_client, name)

def test_create_bucket(s3_client, bucket):
    assert bucket_exists(s3_client, bucket) is True

def test_list_buckets(s3_client, bucket, capsys):
    list_buckets(s3_client)
    
    content = capsys.readouterr()
    assert bucket in content.out

def test_upload_object(args, s3_client, bucket):
    key = "TEST"

    upload_object(s3_client, bucket, key, args.file, False)

    assert object_exists(s3_client, bucket, key) is True