"""Private case storage, resumable uploads and bounded Cloud Tasks dispatch."""

import json
import os
import time
from datetime import datetime, timezone
from uuid import UUID
from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage, tasks_v2
from google.protobuf.duration_pb2 import Duration


def prefix(owner, analysis_id):
    return f"users/{owner}/analyses/{UUID(str(analysis_id))}"


class Cases:
    def __init__(self):
        self.bucket = storage.Client().bucket(os.environ["LASTRADA_CASE_BUCKET"])

    def read(self, path):
        blob = self.bucket.blob(path)
        blob.reload()
        return json.loads(blob.download_as_bytes(if_generation_match=blob.generation)), int(
            blob.generation
        )

    def write(self, path, data, generation=None):
        blob = self.bucket.blob(path)
        kwargs = {} if generation is None else {"if_generation_match": generation}
        blob.upload_from_string(json.dumps(data), content_type="application/json", **kwargs)

    def upload_session(self, path, upload, origin):
        return self.bucket.blob(path).create_resumable_upload_session(
            content_type=upload.content_type, size=upload.size, origin=origin
        )

    def validate_upload(self, path, expected_size):
        blob = self.bucket.blob(path)
        blob.reload()
        if blob.size != expected_size:
            raise ValueError("An upload is incomplete or has the wrong size")

    def stream(self, path):
        with self.bucket.blob(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                yield chunk

    def download(self, path, local_path):
        self.bucket.blob(path).download_to_filename(str(local_path))

    def quota(self, owner):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for key, limit in [
            (owner, int(os.getenv("LASTRADA_USER_DAILY_JOBS", "3"))),
            ("shared", int(os.getenv("LASTRADA_DAILY_JOBS", "20"))),
        ]:
            path = f"quotas/{day}/{key}.json"
            for attempt in range(8):
                try:
                    data, generation = self.read(path)
                except NotFound:
                    data, generation = {"count": 0}, 0
                if data["count"] >= limit:
                    raise ValueError("Today's analysis limit has been reached. Try again tomorrow.")
                try:
                    self.write(
                        path, {"count": data["count"] + 1, "updated": time.time()}, generation
                    )
                    break
                except PreconditionFailed:
                    if attempt == 7:
                        raise ValueError("The analysis queue is busy. Try again shortly.") from None


class Queue:
    def __init__(self):
        self.client = tasks_v2.CloudTasksClient()

    def enqueue(self, owner, analysis_id, operation, task_id):
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.getenv("LASTRADA_REGION", "us-central1")
        parent = self.client.queue_path(project, location, "lastrada-analysis")
        url = os.environ["LASTRADA_WORKER_URL"].rstrip("/")
        self.client.create_task(
            parent=parent,
            task={
                "name": f"{parent}/tasks/{task_id}",
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": url + "/internal/process",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(
                        {
                            "owner": owner,
                            "analysis_id": str(analysis_id),
                            "operation": operation,
                            "task_id": task_id,
                        }
                    ).encode(),
                    "oidc_token": {
                        "service_account_email": os.environ["LASTRADA_TASK_ACCOUNT"],
                        "audience": url,
                    },
                },
                "dispatch_deadline": Duration(seconds=1800),
            },
        )
