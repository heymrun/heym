import unittest
import uuid

from app.services.workflow_executor import execute_workflow


def _node_output(result, node_type: str):
    for nr in result.node_results:
        nr_type = nr["node_type"] if isinstance(nr, dict) else nr.node_type
        if nr_type == node_type:
            return nr["output"] if isinstance(nr, dict) else nr.output
    return None


class FileUploadTriggerExecutorTests(unittest.TestCase):
    def test_uploaded_file_exposed_to_downstream(self) -> None:
        file_payload = {
            "id": "file-123",
            "name": "recording.mp3",
            "mime": "audio/mpeg",
            "size": 2048,
            "download_url": "http://testserver/api/files/file-123",
        }
        nodes = [
            {
                "id": "n1",
                "type": "fileUploadTrigger",
                "data": {
                    "label": "audio",
                    "_initial_inputs": {
                        "file": file_payload,
                        "uploaded_at": "2026-06-25T12:00:00+00:00",
                    },
                },
            },
            {
                "id": "n2",
                "type": "output",
                "data": {"label": "Result", "value": "Got file $audio.file.name"},
            },
        ]
        edges = [{"id": "e1", "source": "n1", "target": "n2"}]

        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs={"headers": {}, "query": {}, "body": {}},
            test_run=True,
        )

        trigger_output = _node_output(result, "fileUploadTrigger")
        self.assertIsNotNone(trigger_output)
        self.assertEqual(trigger_output["file"]["name"], "recording.mp3")
        self.assertEqual(trigger_output["uploaded_at"], "2026-06-25T12:00:00+00:00")
