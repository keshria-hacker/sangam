import json
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FrontendResponseControllerTests(unittest.TestCase):
    def _run_controller_script(self, body: str):
        script = textwrap.dedent(f"""
            import {{ createResponseController }} from {json.dumps((ROOT / 'mainfiles/frontend/js/features/chat/response_controller.js').as_uri())};
            {body}
        """)
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_unknown_event_does_not_crash_or_corrupt_following_events(self):
        seen = self._run_controller_script("""
            const seen = [];
            const controller = createResponseController({
              textDelta: (text) => seen.push(['text', text]),
              unknown: (event) => seen.push(['unknown', event.type]),
              error: (err) => seen.push(['error', err.message]),
            });
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'message_start', message_id:'m1', sequence:0})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'future_event', message_id:'m1', sequence:1})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_start', message_id:'m1', sequence:2})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_delta', message_id:'m1', sequence:3, content:'ok'})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_end', message_id:'m1', sequence:4})});
            controller.flush(); // force flush buffers
            console.log(JSON.stringify(seen));
        """)
        self.assertEqual(seen, [["unknown", "future_event"], ["text", "ok"]])

    def test_wrong_message_id_does_not_poison_sequence_and_terminal_is_unique(self):
        seen = self._run_controller_script("""
            const seen = [];
            const controller = createResponseController({
              textDelta: (text) => seen.push(['text', text]),
              messageEnd: () => seen.push(['end']),
              warning: (message) => seen.push(['warning', message]),
            });
            const send = (payload) => controller.handleSSE({event:'response_event', data:JSON.stringify(payload)});
            send({type:'message_start', message_id:'m1', sequence:0});
            send({type:'text_start', message_id:'other', sequence:50});
            send({type:'text_start', message_id:'m1', sequence:1});
            send({type:'text_delta', message_id:'m1', sequence:2, content:'ok'});
            send({type:'text_end', message_id:'m1', sequence:3});
            send({type:'message_end', message_id:'m1', sequence:4, finish_reason:'stop'});
            send({type:'message_end', message_id:'m1', sequence:5, finish_reason:'stop'});
            controller.flush(); // force flush buffers
            console.log(JSON.stringify(seen));
        """)
        self.assertEqual(seen.count(["end"]), 1)
        self.assertIn(["text", "ok"], seen)

    def test_invalid_lifecycle_is_ignored_without_crashing(self):
        seen = self._run_controller_script("""
            const seen = [];
            const controller = createResponseController({
              textDelta: (text) => seen.push(['text', text]),
              warning: (message) => seen.push(['warning', message]),
            });
            const send = (payload) => controller.handleSSE({event:'response_event', data:JSON.stringify(payload)});
            send({type:'text_delta', message_id:'m1', sequence:0, content:'early'});
            send({type:'message_start', message_id:'m1', sequence:1});
            send({type:'text_delta', message_id:'m1', sequence:2, content:'outside'});
            send({type:'text_start', message_id:'m1', sequence:3});
            send({type:'text_delta', message_id:'m1', sequence:4, content:'valid'});
            controller.flush(); // force flush buffers
            console.log(JSON.stringify(seen));
        """)
        self.assertEqual([item for item in seen if item[0] == "text"], [["text", "valid"]])

    def test_buffer_coalesces_multiple_deltas_before_flush(self):
        """Verify that multiple rapid text_delta events are coalesced into a single flush."""
        seen = self._run_controller_script("""
            const seen = [];
            const controller = createResponseController({
              textDelta: (text) => seen.push(['text', text]),
            });
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'message_start', message_id:'m1', sequence:0})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_start', message_id:'m1', sequence:1})});
            // Send multiple rapid deltas - they should be buffered and coalesced
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_delta', message_id:'m1', sequence:2, content:'Hel'})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_delta', message_id:'m1', sequence:3, content:'lo '})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_delta', message_id:'m1', sequence:4, content:'World'})});
            // Only one textDelta should have fired after flush
            controller.flush();
            console.log(JSON.stringify(seen));
        """)
        # Should get exactly one textDelta with all content coalesced
        self.assertEqual(len([s for s in seen if s[0] == 'text']), 1)
        self.assertEqual(seen[0], ['text', 'Hel' + 'lo ' + 'World'])

    def test_flush_on_text_end(self):
        """Verify text_end triggers automatic flush of buffered content."""
        seen = self._run_controller_script("""
            const seen = [];
            const controller = createResponseController({
              textDelta: (text) => seen.push(['text', text]),
              textEnd: () => seen.push(['textEnd']),
            });
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'message_start', message_id:'m1', sequence:0})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_start', message_id:'m1', sequence:1})});
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_delta', message_id:'m1', sequence:2, content:'Hello'})});
            // text_end should auto-flush
            controller.handleSSE({event: 'response_event', data: JSON.stringify({type:'text_end', message_id:'m1', sequence:3})});
            console.log(JSON.stringify(seen));
        """)
        # textDelta should have fired, then textEnd
        textDeltas = [s for s in seen if s[0] == 'text']
        self.assertEqual(len(textDeltas), 1)
        self.assertEqual(textDeltas[0][1], 'Hello')
        self.assertIn(['textEnd'], seen)
