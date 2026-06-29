from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the s3 node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _coerce_boolean = _workflow_executor._coerce_boolean
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.session import SessionLocal
    from app.services.amazon_s3_service import S3Service, normalize_s3_list_max_keys
    from app.services.encryption import decrypt_config

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Amazon S3 node requires a credential")

    operation = node_data.get("s3Operation", "")
    if not operation:
        raise ValueError("Amazon S3 node requires an operation")

    s3_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            s3_config = decrypt_config(cred.encrypted_config)

    if not s3_config:
        raise ValueError("Amazon S3 credential not found or invalid")

    service = S3Service(s3_config)

    if operation == "listBuckets":
        output = service.list_buckets()
    else:
        bucket = self.evaluate_nonempty_message_template(
            str(node_data.get("s3Bucket", "") or ""), inputs, node_id
        ).strip()
        if not bucket:
            raise ValueError("Amazon S3 bucket is required")

        if operation == "putObject":
            key = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not key:
                raise ValueError("Amazon S3 object key is required")
            body = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Body", "") or ""), inputs, node_id
            )
            content_type = self.evaluate_nonempty_message_template(
                str(node_data.get("s3ContentType", "") or ""), inputs, node_id
            ).strip()
            output = service.put_object(bucket, key, body, content_type or None)
        elif operation == "getObject":
            key = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not key:
                raise ValueError("Amazon S3 object key is required")
            output = service.get_object(
                bucket,
                key,
                include_binary=_coerce_boolean(node_data.get("s3IncludeBinary"), default=False),
            )
        elif operation == "createBucket":
            output = service.create_bucket(
                bucket,
                str(s3_config.get("aws_region", "") or "").strip(),
            )
        elif operation == "deleteBucket":
            output = service.delete_bucket(bucket)
        elif operation == "createFolder":
            folder_path = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not folder_path:
                raise ValueError("Amazon S3 folder path is required")
            output = service.create_folder(bucket, folder_path)
        elif operation == "deleteFolder":
            folder_path = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not folder_path:
                raise ValueError("Amazon S3 folder path is required")
            output = service.delete_folder(bucket, folder_path)
        elif operation == "getAllFolder":
            folder_path = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not folder_path:
                raise ValueError("Amazon S3 folder path is required")
            output = service.get_all_folder(bucket, folder_path)
        elif operation == "copyObject":
            source_bucket = self.evaluate_nonempty_message_template(
                str(node_data.get("s3SourceBucket", "") or ""), inputs, node_id
            ).strip()
            source_key = self.evaluate_nonempty_message_template(
                str(node_data.get("s3SourceKey", "") or ""), inputs, node_id
            ).strip()
            dest_key = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not source_key:
                raise ValueError("Amazon S3 source object key is required")
            if not dest_key:
                raise ValueError("Amazon S3 destination object key is required")
            resolved_source_bucket = source_bucket or bucket
            output = service.copy_object(
                resolved_source_bucket,
                source_key,
                bucket,
                dest_key,
            )
        elif operation == "deleteObject":
            key = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Key", "") or ""), inputs, node_id
            ).strip()
            if not key:
                raise ValueError("Amazon S3 object key is required")
            output = service.delete_object(bucket, key)
        elif operation == "listObjects":
            prefix = self.evaluate_nonempty_message_template(
                str(node_data.get("s3Prefix", "") or ""), inputs, node_id
            ).strip()
            max_keys_template = str(node_data.get("s3MaxKeys", "100") or "100")
            max_keys_raw = self.evaluate_nonempty_message_template(
                max_keys_template, inputs, node_id
            ).strip()
            continuation_token = (
                self.evaluate_nonempty_message_template(
                    str(node_data.get("s3ContinuationToken", "") or ""), inputs, node_id
                ).strip()
                or None
            )
            try:
                max_keys = normalize_s3_list_max_keys(int(float(max_keys_raw or "100")))
            except (TypeError, ValueError):
                max_keys = 100
            output = service.list_objects(
                bucket,
                prefix,
                max_keys,
                continuation_token,
            )
        else:
            raise ValueError(f"Unknown Amazon S3 operation: {operation}")
    return output
