import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
import time

import boto3
from botocore.exceptions import ClientError

## config
def load_config() -> SimpleNamespace:
    # TODO: now we hardcoded porperties
    config = SimpleNamespace(
        # MinIO connections
        minio_endpoint_url="http://localhost:9000",
        minio_region="us-east-1",
        # MinIO credentials
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        # bucket-related
        bucket="simres", # bucket name must be lowercase
        # object related
        file="img.png",
        retention_days=7
    )

    return config

## S3/MinIO client
def create_s3_client(args: SimpleNamespace):
    # explicit session
    session_kwargs = {}
    session_kwargs["aws_access_key_id"] = args.access_key_id
    session_kwargs["aws_secret_access_key"] = args.secret_access_key

    session = boto3.Session(**session_kwargs)

    return session.client(
        "s3",
        endpoint_url=args.minio_endpoint_url,
        region_name=args.minio_region
    )

## bucket-related operations
def bucket_exists(s3_client, bucket: str) -> bool:
    try:
        s3_client.head_bucket(Bucket=bucket)
        return True
    except ClientError as e:
        # https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_bucket.html
        # If the bucket doesn’t exist or you don’t have permission to access it, the HEAD request returns a generic 400 Bad Request, 403 Forbidden, or 404 Not Found HTTP status code. A message body isn’t included, so you can’t determine the exception beyond these HTTP response codes.
        return False

def create_bucket(s3_client, bucket: str):
    if bucket_exists(s3_client, bucket):
        print(f"Bucket {bucket} already exists")
        return
    
    s3_client.create_bucket(
        Bucket=bucket,
        ObjectLockEnabledForBucket=True # Retention: Bucket must enable Object Lock FIRST
    )
    print(f"Bucket {bucket} created")

def list_buckets(s3_client):
    response = s3_client.list_buckets()
    buckets = response.get("Buckets", [])
    
    if not buckets:
        print("No buckets found")
    else:
        print("Buckets:")
        for bucket in buckets:
            print(f"  - {bucket['Name']}")

def delete_bucket(s3_client, bucket: str):
    if not bucket_exists(s3_client, bucket):
        print(f"Bucket {bucket} does not exist")
        return
    
    # verify object versions + markers
    response = s3_client.list_object_versions(Bucket=bucket)

    versions = response.get("Versions", [])
    delete_markers = response.get("DeleteMarkers", [])

    if versions or delete_markers:
        print(
            f"Bucket {bucket} still contains "
            f"object versions or delete markers"
        )
        return

    s3_client.delete_bucket(Bucket=bucket)
    print(f"Bucket {bucket} deleted")

## object-related operations
def object_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        return False

def upload_object(s3_client,
                  bucket: str,
                  key: str,
                  file_path: str,
                  retention: bool,
                  retention_days: int = 0):
    s3_client.upload_file(file_path, bucket, key)
    print(f"Object {key} uploaded to bucket {bucket}")

    if retention:
        s3_client.put_object_retention(
            Bucket=bucket,
            Key=key,
            Retention={
                "Mode": "GOVERNANCE",
                "RetainUntilDate": (datetime.now(timezone.utc) + timedelta(days=retention_days)) # S3/MinIO retention should use timezone-aware UTC timestamps
            }
        )
        print(f"Retention set for object {key} in bucket {bucket}")

def list_objects(s3_client, bucket: str):
    response = s3_client.list_objects_v2(Bucket=bucket)
    objects = response.get("Contents", [])
    
    if not objects:
        print(f"No objects found in bucket {bucket}")
    else:
        print(f"Objects in bucket {bucket}:")
        for obj in objects:
            print(f"  - {obj['Key']}")

def get_object_metadata(s3_client, bucket: str, key: str):
    try:
        response = s3_client.head_object(Bucket=bucket, Key=key)
        print(f"Metadata for object {key} in bucket {bucket}:")
        for k, v in response.items():
            print(f"  - {k}: {v}")
    except ClientError as e:
        # TODO: may be other reasons for failure, not just object not exist
        # TODO: or use object_exists() before calling head_object()
        print(f"Object {key} does not exist in bucket {bucket}")

def download_object(s3_client, bucket: str, key: str, download_path: str):
    if not object_exists(s3_client, bucket, key):
        print(f"Object {key} does not exist in bucket {bucket}")
        return
    
    s3_client.download_file(bucket, key, download_path)
    print(f"Object {key} downloaded to {download_path}")

def delete_object(s3_client, bucket: str, key: str):
    if not object_exists(s3_client, bucket, key):
        print(f"Object {key} does not exist in bucket {bucket}")
        return
    try:
        s3_client.delete_object(Bucket=bucket, Key=key, BypassGovernanceRetention=False)
        print(f"Object {key} deleted from bucket {bucket}")
    except ClientError as e:
        print(f"Error occurred while deleting object {key} from bucket {bucket}: {e}")

def fully_delete_object(s3_client, bucket: str, key: str):
    response = s3_client.list_object_versions(
        Bucket=bucket,
        Prefix=key
    )

    versions = response.get("Versions", [])
    for version in versions:
        if version["Key"] == key:
            try:
                s3_client.delete_object(
                    Bucket=bucket,
                    Key=key,
                    VersionId=version["VersionId"]
                )
                print(f"Deleted version: {version['VersionId']}")
            except ClientError as e:
                print(f"Error occurred while deleting version {version['VersionId']} of object {key} from bucket {bucket}: {e}")

    delete_markers = response.get("DeleteMarkers", [])
    for marker in delete_markers:
        if marker["Key"] == key:
            s3_client.delete_object(
                Bucket=bucket,
                Key=key,
                VersionId=marker["VersionId"]
            )
            print(f"Deleted delete marker: {marker['VersionId']}")

# TODO: instead, we can set bypass governance retention when deleting the object, which will work even if the object is under retention
def remove_object_retention(s3_client, bucket: str, key: str):
    response = s3_client.list_object_versions(
        Bucket=bucket,
        Prefix=key
    )

    versions = response.get("Versions", [])

    for version in versions:
        if version["Key"] == key:
            s3_client.put_object_retention(
                Bucket=bucket,
                Key=key,
                VersionId=version["VersionId"], # IMPORTANT!!
                Retention={
                    "Mode": "GOVERNANCE",
                    "RetainUntilDate": (datetime.now(timezone.utc) + timedelta(seconds=1))
                },
                BypassGovernanceRetention=True
            )

            print(f"Retention removed for object {key}, version {version['VersionId']} in bucket {bucket}")

    time.sleep(1)

def main() -> int:
    args = load_config()

    # connect to MinIO
    s3_client = create_s3_client(args)

    # list all bucket
    list_buckets(s3_client)

    # create bucket
    create_bucket(s3_client, args.bucket)

    # list all bucket
    list_buckets(s3_client)

    # list all objects
    list_objects(s3_client, args.bucket)

    # upload file 1
    # TODO: hardcoded key
    upload_object(s3_client, args.bucket, "OBJECT_1", args.file, False)

    # update file 2 with 7 day retention
    # TODO: hardcoded key
    upload_object(s3_client, args.bucket, "OBJECT_2", args.file, True, args.retention_days)

    # list all objects
    list_objects(s3_client, args.bucket)

    # get metadata of object 1
    get_object_metadata(s3_client, args.bucket, "OBJECT_1")

    # download object 1
    download_object(s3_client, args.bucket, "OBJECT_1", datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".png")

    # delete object 1
    delete_object(s3_client, args.bucket, "OBJECT_1")

    # delete object 2
    delete_object(s3_client, args.bucket, "OBJECT_2")

    # list all objects
    list_objects(s3_client, args.bucket)

    # fully delete object 1
    fully_delete_object(s3_client, args.bucket, "OBJECT_1")

    # fully delete object 2
    fully_delete_object(s3_client, args.bucket, "OBJECT_2")

    # delete bucket
    delete_bucket(s3_client, args.bucket)

    # remove retention of object 2
    remove_object_retention(s3_client, args.bucket, "OBJECT_2")

    # fully delete object 2
    fully_delete_object(s3_client, args.bucket, "OBJECT_2")

    # delete bucket
    delete_bucket(s3_client, args.bucket)
    
    # list all bucket
    list_buckets(s3_client)

    return 0

if __name__ == "__main__":
    sys.exit(main())