import ast
import hashlib
import io
import json
import os
from collections import defaultdict
from pathlib import Path
import tempfile
import types
import unittest

from scripts.civitai_storage import is_model_sidecar, read_json, write_json, enough_space


def load_version_match():
    # The full extension needs WebUI and Gradio. Isolate the pure matching logic.
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_file_manage.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'version_match')
    scope = {'os': os, 'read_json': read_json, 'gl': types.SimpleNamespace()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['version_match'], scope['gl']


def load_settings_writer(config):
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_gui.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'saveSettings')
    scope = {'cmd_opts': types.SimpleNamespace(ui_config_file=str(config)),
             'read_json': read_json, 'write_json': write_json, 'print': lambda _: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['saveSettings']


def load_gen_sha256():
    # Needs os/io/hashlib plus the storage helpers; no WebUI or Gradio import.
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_file_manage.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'gen_sha256')
    scope = {'os': os, 'io': io, 'hashlib': hashlib,
             'read_json': read_json, 'write_json': write_json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['gen_sha256']


def load_download_file():
    # Isolate the aria2 path to assert the reported final path, not the transfer path.
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_download.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'download_file')
    printed = []
    scope = {'os': os, 'json': json, 'time': types.SimpleNamespace(sleep=lambda _: None),
             'opts': types.SimpleNamespace(), 'queue': False,
             'gl': types.SimpleNamespace(), 'gr': types.SimpleNamespace(Progress=None),
             'requests': types.SimpleNamespace(post=lambda *a, **k: None),
             'rpc_secret': 'test-secret',
             'get_download_link': lambda *a: 'https://example.invalid/model.safetensors',
             'convert_size': lambda n: str(n),
             'current_count': 0, 'total_count': 0,
             'print': lambda msg: printed.append(msg)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['download_file'], scope, printed


def load_cancel_helpers():
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_download.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    wanted = {'download_cancel', 'download_cancel_all', 'await_download_stop'}
    nodes = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    scope = {'time': types.SimpleNamespace(sleep=lambda _: None),
             'CANCEL_WAIT_LIMIT': 1200,
             'gl': types.SimpleNamespace(),
             '_file': types.SimpleNamespace(delete_model=lambda *a, **k: None),
             'print': lambda msg: None}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def load_version_list_updater(installed_names, installed_hashes):
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_api.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'update_model_versions')
    scope = {'os': os, 'defaultdict': defaultdict,
             'gl': types.SimpleNamespace(json_data={}),
             'contenttype_folder': lambda *a, **k: 'models',
             'installed_inventory': lambda folder: (installed_names, installed_hashes),
             'gr': types.SimpleNamespace(
                 Dropdown=types.SimpleNamespace(update=lambda **kw: dict(kw)))}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['update_model_versions']


def load_overview_functions():
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_file_manage.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    wanted = {'version_overview_rows', 'render_version_overview'}
    nodes = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    scope = {'os': os, 'escape': lambda value: str(value).replace('<', '&lt;').replace('>', '&gt;')}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def load_download_worker():
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_download.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'download_create_thread')
    printed = []

    def boom(path):
        raise RuntimeError('make_dir boom')

    scope = {
        'os': os, 'json': json, 'Path': Path,
        'time': types.SimpleNamespace(sleep=lambda _: None),
        'threading': types.SimpleNamespace(
            Thread=types.SimpleNamespace()),
        'gl': types.SimpleNamespace(),
        'opts': types.SimpleNamespace(),
        'os_type': 'Linux',
        'ZipHandler': None,
        'current_count': 0, 'total_count': 0,
        # Default arguments are evaluated at def time, so both must exist here.
        'queue': False,
        'gr_progress_threadable': lambda: None,
        'gr': types.SimpleNamespace(
            HTML=types.SimpleNamespace(update=lambda **kw: kw),
            Textbox=types.SimpleNamespace(update=lambda **kw: kw),
            Button=types.SimpleNamespace(update=lambda **kw: kw)),
        '_api': types.SimpleNamespace(update_model_versions=lambda *a, **k: {},
                                     update_model_info=lambda *a, **k: None,
                                     invalidate_inventory=lambda: None),
        '_file': types.SimpleNamespace(make_dir=boom,
                                       save_model_info=lambda *a, **k: None,
                                       save_preview=lambda *a, **k: None,
                                       save_images=lambda *a, **k: None,
                                       card_update=lambda *a, **k: (None, None, None)),
        'enough_space': lambda *a, **k: (True, 10 ** 12),
        'convert_size': lambda n: str(n),
        'info_to_json': lambda *a, **k: None,
        'download_file': lambda *a, **k: None,
        'download_file_old': lambda *a, **k: None,
        'download_manager_html': lambda html: html,
        'random_number': lambda value: value,
        'print': printed.append,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['download_create_thread'], scope, printed


def load_queue_all(items, receiver):
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_download.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'queue_all_updates')
    scope = {'gl': types.SimpleNamespace(update_items=items), 'json': json,
             'selected_to_queue': receiver}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['queue_all_updates']


class RegressionTests(unittest.TestCase):
    def test_invalid_other_extension_sidecar_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'model.safetensors').touch()
            Path(folder, 'model.cm-info.json').touch()
            self.assertFalse(is_model_sidecar(folder, 'model.cm-info.json'))
            self.assertTrue(is_model_sidecar(folder, 'model.json'))

    def test_atomic_write_preserves_existing_metadata_on_error(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, 'model.json')
            write_json(target, {'setting': 'keep'})
            with self.assertRaises(TypeError):
                write_json(target, {'bad': object()})
            self.assertEqual(read_json(target), {'setting': 'keep'})

    def test_settings_writer_preserves_other_extension_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder, 'ui-config.json')
            write_json(config, {'other_extension/value': 'keep',
                                'civitai_interface/custom/value': 'also keep'})
            load_settings_writer(config)(*range(12))
            data = read_json(config)
            self.assertEqual(data['other_extension/value'], 'keep')
            self.assertEqual(data['civitai_interface/custom/value'], 'also keep')
            self.assertEqual(data['civitai_interface/Tile count:/value'], 11)

    def test_update_stays_with_installed_base_model(self):
        match, state = load_version_match()
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder, 'installed.safetensors')
            model.touch()
            write_json(model.with_suffix('.json'), {
                'modelId': 7, 'modelVersionId': 20, 'sha256': 'ABCD'
            })
            item = {'id': 7, 'name': 'Example', 'modelVersions': [
                {'id': 30, 'baseModel': 'Krea', 'files': []},
                {'id': 20, 'baseModel': 'Qwen', 'files': []},
            ]}
            self.assertEqual(match([str(model)], {'items': [item]})[1], [])
            self.assertEqual(match([str(model)], {'items': [item]}, True)[1], [('&ids=7', 'Example')])
            self.assertEqual(state.update_preferred_versions['7'], 30)
            item['modelVersions'].insert(0, {'id': 31, 'baseModel': 'Qwen', 'files': []})
            self.assertEqual(match([str(model)], {'items': [item]})[1], [('&ids=7', 'Example')])
            self.assertEqual(state.update_preferred_versions['7'], 31)

    def test_space_check_uses_destination_volume(self):
        with tempfile.TemporaryDirectory() as folder:
            free = enough_space(folder, 0, reserve=0)[1]
            self.assertTrue(enough_space(folder, 0, reserve=0)[0])
            self.assertFalse(enough_space(folder, free + 1, reserve=0)[0])

    def test_gen_sha256_persists_hash_when_sidecar_is_corrupt(self):
        # The old code re-read the sidecar with a raw json.load, so a corrupt file
        # threw before the write and the computed hash was thrown away silently.
        gen_sha256 = load_gen_sha256()
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder, 'model.safetensors')
            model.write_bytes(b'payload')
            model.with_suffix('.json').write_text('{not valid json', encoding='utf-8')
            value = gen_sha256(str(model))
            self.assertEqual(value, hashlib.sha256(b'payload').hexdigest())
            self.assertEqual(read_json(model.with_suffix('.json')), {'sha256': value})

    def test_gen_sha256_keeps_existing_metadata_and_reuses_cached_hash(self):
        gen_sha256 = load_gen_sha256()
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder, 'model.safetensors')
            model.write_bytes(b'payload')
            sidecar = model.with_suffix('.json')
            write_json(sidecar, {'modelId': 7, 'modelVersionId': 20})
            value = gen_sha256(str(model))
            stored = read_json(sidecar)
            self.assertEqual(stored['sha256'], value)
            self.assertEqual(stored['modelId'], 7)
            self.assertEqual(stored['modelVersionId'], 20)
            model.write_bytes(b'changed behind our back')
            self.assertEqual(gen_sha256(str(model)), value)

    def test_aria2_download_reports_final_path_not_transfer_path(self):
        download_file, scope, printed = load_download_file()

        class Response:
            @staticmethod
            def post(*_args, **_kwargs):
                return types.SimpleNamespace(text=json.dumps({'result': 'gid-1'}))

        class Status:
            calls = 0

            @staticmethod
            def post(*_args, **_kwargs):
                Status.calls += 1
                if Status.calls == 1:
                    payload = {'result': {'totalLength': '10', 'completedLength': '5',
                                          'downloadSpeed': '1', 'status': 'active'}}
                else:
                    payload = {'result': {'totalLength': '10', 'completedLength': '10',
                                          'downloadSpeed': '0', 'status': 'complete'}}
                return types.SimpleNamespace(text=json.dumps(payload))

        scope['requests'] = types.SimpleNamespace(post=Status.post)
        scope['time'] = types.SimpleNamespace(sleep=lambda _: None)
        scope['gl'].cancel_status = False
        scope['gl'].download_fail = False
        with tempfile.TemporaryDirectory() as folder:
            transfer = os.path.join(folder, 'model.safetensors.civitai-part')
            download_file('url', transfer, folder, 7, None)
        self.assertTrue(any(str(os.path.join(folder, 'model.safetensors')) in line
                            for line in printed), printed)
        self.assertFalse(any(transfer in line for line in printed), printed)

    def test_cancel_helpers_do_not_hang_and_clear_queue(self):
        scope = load_cancel_helpers()
        scope['gl'].download_queue = [{'model_name': 'Example', 'model_id': 7,
                                       'model_filename': 'model.safetensors',
                                       'version_name': 'v1', 'model_versions': [],
                                       'model_json': {}}]
        scope['gl'].isDownloading = False
        scope['download_cancel']()
        self.assertTrue(scope['gl'].cancel_status)
        scope['gl'].isDownloading = False
        scope['download_cancel_all']()
        self.assertEqual(scope['gl'].download_queue, [])

    def test_cancel_wait_gives_up_instead_of_spinning_forever(self):
        scope = load_cancel_helpers()
        scope['gl'].isDownloading = True
        self.assertFalse(scope['await_download_stop'](limit=3))

    def test_failed_item_does_not_wedge_the_download_queue(self):
        # Regression: an exception used to escape before the queue was popped, so the
        # finished item stayed at index 0 and isDownloading stayed True. Every later
        # download then saw a non-empty queue and refused to start.
        worker, scope, printed = load_download_worker()
        item = {'from_batch': False, 'model_name': 'Example', 'model_id': 7,
                'version_name': 'v1.0', 'model_filename': 'model.safetensors',
                'install_path': '/tmp/irrelevant', 'size_bytes': 0, 'dl_url': 'x',
                'model_versions': {}, 'model_json': {}, 'sub_folder': '',
                'create_json': False, 'model_sha256': '', 'version_id': 1}
        scope['gl'].download_queue = [item]
        scope['gl'].isDownloading = False
        worker('finish', 'queue', None)
        self.assertEqual(scope['gl'].download_queue, [])
        self.assertFalse(scope['gl'].isDownloading)
        self.assertTrue(scope['gl'].download_fail)
        # Proves the except branch caught our error rather than a scope NameError.
        self.assertTrue(any('make_dir boom' in line for line in printed), printed)

    def test_queue_survives_remaining_items_after_a_failure(self):
        worker, scope, printed = load_download_worker()
        first = {'from_batch': False, 'model_name': 'First', 'model_id': 7,
                 'version_name': 'v1', 'model_filename': 'a.safetensors',
                 'install_path': '/tmp/irrelevant', 'size_bytes': 0, 'dl_url': 'x',
                 'model_versions': {}, 'model_json': {}, 'sub_folder': '',
                 'create_json': False, 'model_sha256': '', 'version_id': 1}
        second = dict(first, model_name='Second', model_filename='b.safetensors')
        scope['gl'].download_queue = [first, second]
        scope['gl'].isDownloading = False
        worker('finish', 'queue', None)
        self.assertEqual(scope['gl'].download_queue, [second])
        self.assertFalse(scope['gl'].isDownloading)

    def test_installed_version_is_detected_by_plain_filename(self):
        # The old code only compared the file-id form, so a model with no stored
        # sha256 was never reported as installed.
        item = {'id': 7, 'name': 'Example', 'type': 'Checkpoint', 'description': 'None',
                'modelVersions': [
                    {'id': 20, 'name': 'v1.0', 'baseModel': 'SDXL',
                     'files': [{'id': 555, 'name': 'example.safetensors', 'hashes': {}}]},
                    {'id': 21, 'name': 'v2.0', 'baseModel': 'SDXL',
                     'files': [{'id': 556, 'name': 'other.safetensors', 'hashes': {}}]},
                ]}
        update = load_version_list_updater({'example.safetensors'}, set())
        result = update(7, {'items': [item]})
        self.assertEqual(result['choices'], ['v1.0 [Installed]', 'v2.0'])
        self.assertEqual(result['value'], 'v1.0 [Installed]')

    def test_installed_default_selection_follows_api_order(self):
        # installed_versions was an unordered set, so the preselected entry could
        # change between runs. It must follow the order the API returned.
        item = {'id': 7, 'name': 'Example', 'type': 'Checkpoint', 'description': 'None',
                'modelVersions': [
                    {'id': 30, 'name': 'v2.0', 'baseModel': 'SDXL',
                     'files': [{'id': 1, 'name': 'b.safetensors', 'hashes': {}}]},
                    {'id': 20, 'name': 'v1.0', 'baseModel': 'SDXL',
                     'files': [{'id': 2, 'name': 'a.safetensors', 'hashes': {}}]},
                ]}
        update = load_version_list_updater({'a.safetensors', 'b.safetensors'}, set())
        for _ in range(5):
            self.assertEqual(update(7, {'items': [item]})['value'], 'v2.0 [Installed]')

    def test_version_overview_marks_installed_by_name_and_by_sha(self):
        scope = load_overview_functions()
        rows_for = scope['version_overview_rows']
        item = {'modelVersions': [
            {'id': 20, 'name': 'v1.0', 'baseModel': 'SDXL',
             'files': [{'id': 1, 'name': 'example.safetensors', 'hashes': {}}]},
            {'id': 21, 'name': 'v2.0', 'baseModel': 'SD 1.5',
             'files': [{'id': 2, 'name': 'other.safetensors', 'hashes': {'SHA256': 'ABC'}}]},
        ]}
        by_name = rows_for(item, {'example.safetensors'}, set())
        self.assertTrue(by_name[0]['installed'])
        self.assertFalse(by_name[1]['installed'])
        by_sha = rows_for(item, set(), {'ABC'})
        self.assertFalse(by_sha[0]['installed'])
        self.assertTrue(by_sha[1]['installed'])
        self.assertEqual(by_sha[1]['base_model'], 'SD 1.5')
        self.assertEqual(by_sha[1]['version_id'], 21)
        # The file-id layout is accepted too.
        by_id_form = rows_for(item, {'example_1.safetensors'}, set())
        self.assertTrue(by_id_form[0]['installed'])

    def test_render_version_overview_reports_state(self):
        scope = load_overview_functions()
        render = scope['render_version_overview']
        overview = [{'model_id': 7, 'model_name': 'Example', 'folder': 'models',
                     'versions': [
                         {'name': 'v1.0', 'version_id': 20, 'base_model': 'SDXL',
                          'files': [{'name': 'a.safetensors', 'sha256': '', 'installed': True}],
                          'installed': True},
                         {'name': 'v2.0', 'version_id': 21, 'base_model': 'SD 1.5',
                          'files': [{'name': 'b.safetensors', 'sha256': '', 'installed': False}],
                          'installed': False}]}]
        html = render(overview)
        self.assertIn('Example', html)
        self.assertIn('v1.0', html)
        self.assertIn('Installed', html)
        self.assertIn('SD 1.5', html)
        self.assertIn('No installed models', render([]))

    def test_queue_all_uses_every_scan_result(self):
        items = [{'id': 1, 'name': 'First'}, {'id': 2, 'name': 'Last page'}]
        captured = []
        fn = load_queue_all(items, lambda *args: captured.append(args))
        fn('start', True, 'html')
        self.assertEqual(json.loads(captured[0][0]), ['First (1)', 'Last page (2)'])
        self.assertEqual(captured[0][-1]['items'], items)


if __name__ == '__main__':
    unittest.main()
