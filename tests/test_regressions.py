import ast
import hashlib
import sys
import io
import json
import os
import time
from collections import OrderedDict
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import types
import unittest

from scripts.civitai_storage import is_model_sidecar, read_json, write_json, enough_space

import shlex


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


def load_aria2_starter():
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_download.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'start_aria2_rpc')
    recorded = {}
    printed = []

    class FakeSubprocess:
        DEVNULL = object()
        STDOUT = object()

        @staticmethod
        def Popen(args, **kwargs):
            recorded['args'] = args
            recorded['kwargs'] = kwargs

    scope = {'os': os, 'shlex': shlex,
             'time': types.SimpleNamespace(sleep=lambda _: None),
             'subprocess': FakeSubprocess,
             'opts': types.SimpleNamespace(), 'os_type': 'Linux',
             'aria2path': '/tmp/aria2-for-tests', 'aria2': '/tmp/aria2-for-tests/lin/aria2',
             'stop_rpc': ['pkill', 'aria2'], 'rpc_secret': 'unit-test-secret',
             'print': printed.append}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['start_aria2_rpc'], scope, recorded, printed


def load_deletion_helpers():
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_file_manage.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    wanted = {'deletion_candidates', 'deletion_plan', 'execute_deletion'}
    nodes = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    scope = {'os': os, 'send2trash': lambda path: scope['trashed'].append(path)}
    scope['trashed'] = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def load_inventory():
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_api.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    wanted = {'installed_inventory', 'invalidate_inventory', '_remember_inventory'}
    nodes = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    scope = {'os': os, 'time': time, 'read_json': read_json,
             'OrderedDict': OrderedDict,
             'MODEL_EXTENSIONS': {'.safetensors', '.ckpt', '.pt', '.pth', '.th', '.zip', '.vae'},
             'gl': types.SimpleNamespace()}
    scope['_inventory_cache'] = OrderedDict()
    scope['_inventory_cache_max'] = 3
    scope['_inventory_ttl'] = 20
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope


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

    def test_aria2_flags_are_not_shell_interpreted(self):
        # aria2_flags is a free-text setting. It used to be interpolated into a
        # "shell=True" command string, so a value like "; rm -rf ~" executed.
        starter, scope, recorded, printed = load_aria2_starter()
        with tempfile.TemporaryDirectory() as folder:
            scope['aria2path'] = folder
            scope['aria2'] = os.path.join(folder, 'lin', 'aria2')
            scope['opts'].aria2_flags = '; rm -rf /tmp/nope && echo pwned'
            scope['opts'].show_log = False
            starter()
        # The starter swallows failures, so prove it actually reached Popen.
        self.assertFalse([line for line in printed if 'Failed to start' in line], printed)
        self.assertIsInstance(recorded['args'], list)
        self.assertNotIn('shell', recorded['kwargs'])
        self.assertFalse(recorded['kwargs'].get('shell', False))
        # The injected text is split into separate argv entries, never concatenated
        # into one command line, and no entry contains a shell metacharacter chain.
        self.assertIn(';', recorded['args'])
        self.assertIn('&&', recorded['args'])
        for entry in recorded['args']:
            self.assertNotIn('&& echo', str(entry))

    def test_aria2_rpc_is_not_exposed_on_all_interfaces(self):
        # The client only ever calls http://localhost:24000 below, so listening on
        # every interface exposed the download RPC to the whole network.
        starter, scope, recorded, printed = load_aria2_starter()
        with tempfile.TemporaryDirectory() as folder:
            scope['aria2path'] = folder
            scope['aria2'] = os.path.join(folder, 'lin', 'aria2')
            scope['opts'].aria2_flags = ''
            scope['opts'].show_log = True
            starter()
        self.assertNotIn('--rpc-listen-all', recorded['args'])
        self.assertIn('--rpc-listen-port=24000', recorded['args'])
        self.assertIn('--rpc-secret=unit-test-secret', recorded['args'])

    def test_aria2_extra_flags_are_appended_as_separate_arguments(self):
        starter, scope, recorded, printed = load_aria2_starter()
        with tempfile.TemporaryDirectory() as folder:
            scope['aria2path'] = folder
            scope['aria2'] = os.path.join(folder, 'lin', 'aria2')
            scope['opts'].aria2_flags = '--max-overall-download-limit=1M --seed-time=10'
            scope['opts'].show_log = False
            starter()
        self.assertFalse([line for line in printed if 'Failed to start' in line], printed)
        self.assertEqual(recorded['args'][-2:],
                         ['--max-overall-download-limit=1M', '--seed-time=10'])

    def test_deletion_candidates_keep_the_newest_installed_version(self):
        # The user asked for a way to spot old versions. Everything installed
        # except the newest is offered for removal; the newest stays.
        scope = load_deletion_helpers()
        overview = [{
            'model_id': 7, 'model_name': 'Example', 'folder': '/models',
            'versions': [
                {'name': 'v3.0', 'version_id': 30, 'base_model': 'SDXL',
                 'files': [{'name': 'c.safetensors', 'installed': True}], 'installed': True},
                {'name': 'v2.0', 'version_id': 20, 'base_model': 'SDXL',
                 'files': [{'name': 'b.safetensors', 'installed': True}], 'installed': True},
                {'name': 'v1.0', 'version_id': 10, 'base_model': 'SDXL',
                 'files': [{'name': 'a.safetensors', 'installed': True}], 'installed': True},
            ]}]
        candidates = scope['deletion_candidates'](overview)
        labels = [entry['label'] for entry in candidates]
        self.assertEqual(labels, ['Example - v2.0', 'Example - v1.0'])
        self.assertEqual([entry['version_id'] for entry in candidates], [20, 10])

    def test_deletion_candidates_skip_models_with_only_one_version(self):
        scope = load_deletion_helpers()
        overview = [{
            'model_id': 7, 'model_name': 'Solo', 'folder': '/models',
            'versions': [
                {'name': 'v1.0', 'version_id': 10, 'base_model': 'SDXL',
                 'files': [{'name': 'a.safetensors', 'installed': True}], 'installed': True},
                {'name': 'v0.9', 'version_id': 9, 'base_model': 'SDXL',
                 'files': [{'name': 'old.safetensors', 'installed': False}], 'installed': False},
            ]}]
        self.assertEqual(scope['deletion_candidates'](overview), [])

    def test_deletion_plan_includes_sidecar_files(self):
        scope = load_deletion_helpers()
        candidates = [{'label': 'Example - v1.0', 'model_id': 7, 'version_id': 10,
                       'model_folder': '/models', 'files': ['a.safetensors']}]
        plan = scope['deletion_plan'](candidates, ['Example - v1.0'])
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]['model_file'], os.path.join('/models', 'a.safetensors'))
        names = [os.path.basename(p) for p in plan[0]['sidecars']]
        self.assertEqual(names, ['a.json', 'a.preview.png', 'a.api_info.json'])

    def test_deletion_plan_ignores_unselected(self):
        scope = load_deletion_helpers()
        candidates = [{'label': 'Example - v1.0', 'model_id': 7, 'version_id': 10,
                       'model_folder': '/models', 'files': ['a.safetensors']}]
        self.assertEqual(scope['deletion_plan'](candidates, []), [])
        self.assertEqual(scope['deletion_plan'](candidates, ['Something else']), [])

    def test_execute_deletion_requires_confirmation(self):
        # The explicit requirement: without the confirm checkbox nothing is deleted.
        scope = load_deletion_helpers()
        plan = [{'label': 'Example - v1.0',
                 'model_file': '/models/a.safetensors',
                 'sidecars': ['/models/a.json', '/models/a.preview.png',
                              '/models/a.api_info.json']}]
        moved, message = scope['execute_deletion'](plan, confirmed=False)
        self.assertEqual(moved, [])
        self.assertEqual(scope['trashed'], [])
        self.assertIn('NOT deleted', message)

    def test_execute_deletion_moves_to_trash_when_confirmed(self):
        scope = load_deletion_helpers()
        with tempfile.TemporaryDirectory() as folder:
            model_file = Path(folder, 'a.safetensors')
            model_file.write_bytes(b'x')
            sidecar = Path(folder, 'a.json')
            sidecar.write_text('{}', encoding='utf-8')
            plan = [{'label': 'Example - v1.0', 'model_file': str(model_file),
                     'sidecars': [str(sidecar),
                                  str(Path(folder, 'a.preview.png'))]}]
            moved, message = scope['execute_deletion'](plan, confirmed=True)
        self.assertEqual(len(moved), 2)  # model + existing sidecar, missing preview skipped
        self.assertIn('Moved 2 file(s) to the trash.', message)
        self.assertEqual(len(scope['trashed']), 2)

    def test_execute_deletion_with_empty_plan_reports_nothing_selected(self):
        scope = load_deletion_helpers()
        moved, message = scope['execute_deletion']([], confirmed=True)
        self.assertEqual(moved, [])
        self.assertIn('Nothing selected', message)

    def test_inventory_cache_is_bounded(self):
        # The cache used to grow one entry per model folder for the whole session.
        scope = load_inventory()
        for index in range(6):
            scope['_remember_inventory'](f'/models/{index}', (time.monotonic(),
                                                            {'n'}, {'h'}, {}))
        self.assertLessEqual(len(scope['_inventory_cache']), 3)

    def test_inventory_cache_evicts_least_recently_used(self):
        scope = load_inventory()
        for name in ('a', 'b', 'c'):
            scope['_remember_inventory'](name, (time.monotonic(), set(), set(), {}))
        scope['_remember_inventory']('a', (time.monotonic(), set(), set(), {}))
        scope['_remember_inventory']('d', (time.monotonic(), set(), set(), {}))
        self.assertIn('a', scope['_inventory_cache'])
        self.assertNotIn('b', scope['_inventory_cache'])  # least recent, not touched
        self.assertIn('c', scope['_inventory_cache'])
        self.assertIn('d', scope['_inventory_cache'])

    def test_scan_clears_running_flag_when_the_scan_raises(self):
        # file_scan used to reset gl.scan_files by hand at nine separate return
        # points. Any exception in between left it on forever and blocked further
        # scans permanently. One finally now covers every exit path.
        scan, scope = load_file_scan()
        scope['gl'].scan_files = False
        with self.assertRaises(RuntimeError):
            scan(['All'], 'ver', 'tag', 'inst', 'prev', False, 0, False, False)
        self.assertFalse(scope['gl'].scan_files,
                         'gl.scan_files stayed True after a failed scan')

    def test_scan_clears_running_flag_on_the_no_selection_path(self):
        scan, scope = load_file_scan()
        # The GUI always enters the scan from one of the four modes; file_scan
        # assigns its trigger number inside those branches. Mirror that here.
        scope['from_ver'] = True
        scope['gl'].scan_files = False
        scan([], 'ver', 'tag', 'inst', 'prev', False, 0, False, False)
        self.assertFalse(scope['gl'].scan_files)

    def test_queue_all_uses_every_scan_result(self):
        items = [{'id': 1, 'name': 'First'}, {'id': 2, 'name': 'Last page'}]
        captured = []
        fn = load_queue_all(items, lambda *args: captured.append(args))
        fn('start', True, 'html')
        self.assertEqual(json.loads(captured[0][0]), ['First (1)', 'Last page (2)'])
        self.assertEqual(captured[0][-1]['items'], items)


if __name__ == '__main__':
    unittest.main()


def load_file_scan():
    """Load file_scan with stubs that let us drive the failure path."""
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_file_manage.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'file_scan')

    def boom(*_args, **_kwargs):
        raise RuntimeError('scan blew up')

    scope = {
        'os': os, 'json': json, 'time': types.SimpleNamespace(sleep=lambda _: None),
        'gr': types.SimpleNamespace(
            HTML=types.SimpleNamespace(update=lambda **kw: kw),
            Textbox=types.SimpleNamespace(update=lambda **kw: kw)),
        'gl': types.SimpleNamespace(scan_files=False, update_items=[], json_data={}),
        '_api': types.SimpleNamespace(get_proxies=lambda: ({}, True),
                                      invalidate_inventory=lambda: None),
        '_file': types.SimpleNamespace(get_content_choices=boom),
        '_download': types.SimpleNamespace(random_number=lambda value: value),
        'from_ver': False, 'from_tag': False, 'from_installed': False,
        'from_preview': False, 'no_update': False, 'queue': False,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['file_scan'], scope


class _AttrCollector(HTMLParser):
    """Parse sanitized output so tests assert on attributes, not substrings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.attrs.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.attrs.append((tag, dict(attrs)))


def _event_handler_attrs(markup):
    parser = _AttrCollector()
    parser.feed(markup)
    parser.close()
    return [name for _tag, attrs in parser.attrs
            for name in attrs if name.lower().startswith('on')]


def _attribute_values(markup, tag_name):
    parser = _AttrCollector()
    parser.feed(markup)
    parser.close()
    return [attrs for tag, attrs in parser.attrs if tag == tag_name]


class SanitizerTests(unittest.TestCase):
    """Regression guards for the XSS paths Eve found in update_model_info."""

    def setUp(self):
        from scripts.civitai_storage import sanitize_model_html
        self.sanitize = sanitize_model_html

    def test_script_tag_is_removed_with_its_body(self):
        self.assertEqual(self.sanitize('<script>alert(1)</script>hi'), 'hi')

    def test_event_handlers_are_stripped(self):
        out = self.sanitize('<img src="https://x.test/a.png" onerror="alert(1)">')
        self.assertEqual(_event_handler_attrs(out), [])
        self.assertIn('https://x.test/a.png', out)

    def test_unquoted_event_handler_is_stripped(self):
        out = self.sanitize('<img src=x onerror=alert(1)>')
        self.assertEqual(_event_handler_attrs(out), [])

    def test_quotes_inside_an_attribute_cannot_inject_a_handler(self):
        # The payload closes the alt value and tries to open a real onload. The
        # whole thing has to end up as inert text inside the alt value.
        out = self.sanitize('<img src="https://x.test/a.png" alt=\'a" onload="alert(1)\'>')
        self.assertEqual(_event_handler_attrs(out), [])
        self.assertEqual(_attribute_values(out, 'img'),
                         [{'src': 'https://x.test/a.png',
                           'alt': 'a" onload="alert(1)'}])

    def test_relative_src_without_scheme_is_dropped(self):
        # Not an over-strict test: a bare "x" is not a usable URL and is exactly
        # the kind of value that would otherwise smuggle a payload.
        self.assertEqual(_attribute_values(self.sanitize('<img src="x">'), 'img'), [{}])

    def test_javascript_url_is_dropped(self):
        out = self.sanitize('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn('javascript:', out)
        for attrs in _attribute_values(out, 'a'):
            self.assertNotIn('href', attrs)

    def test_data_url_in_src_is_dropped(self):
        out = self.sanitize('<img src="data:text/html;base64,PHNjcmlwdD4=">')
        for attrs in _attribute_values(out, 'img'):
            self.assertNotIn('src', attrs)

    def test_iframe_and_svg_are_dropped(self):
        for payload in ('<iframe src="https://x.test"></iframe>',
                        '<svg onload="alert(1)"></svg>'):
            out = self.sanitize(payload)
            self.assertNotIn('<iframe', out)
            self.assertNotIn('<svg', out)
            self.assertEqual(_event_handler_attrs(out), [])

    def test_legitimate_civitai_markup_survives(self):
        # Escaping instead of sanitizing would break the preview entirely.
        raw = ('<p>hello <strong>world</strong></p>'
               '<img src="https://image.civitai.com/x.png">'
               '<code>print(1)</code>'
               '<a href="https://civitai.com/models/1">link</a>')
        out = self.sanitize(raw)
        self.assertIn('<strong>world</strong>', out)
        self.assertIn('<code>', out)
        self.assertEqual(_attribute_values(out, 'img'),
                         [{'src': 'https://image.civitai.com/x.png'}])
        self.assertEqual(_attribute_values(out, 'a'),
                         [{'href': 'https://civitai.com/models/1'}])

    def test_empty_and_none_input(self):
        self.assertEqual(self.sanitize(''), '')
        self.assertEqual(self.sanitize(None), '')

    def test_api_module_has_no_raw_html_interpolation_left(self):
        # Source-level guard so a future edit cannot silently reintroduce one of
        # the four call sites that were vulnerable.
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_api.py')
        text = source.read_text(encoding='utf-8')
        for pattern in ('src={uploader_avatar}', 'src="{image}"',
                        'src="{image_url}"', 'src="{model_desc}"',
                        'href={model_url}', "'{item[\"type\"]}"):
            self.assertNotIn(pattern, text, f'reintroduced raw interpolation: {pattern}')

    def test_queue_html_has_no_raw_item_interpolation(self):
        # download_manager_html builds its markup with a triple-quoted f-string, so
        # the tag sits on the line AFTER the f'''. A one-line regex cannot see that
        # and reported the queue panel as clean when it was not. This guard asserts on
        # the pattern itself rather than on any search we might run.
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'civitai_download.py')
        text = source.read_text(encoding='utf-8')
        for pattern in ('title="{item[\'model_name\']}"',
                        'title="{item[\'version_name\']}"',
                        'title="{item[\'install_path\']}"'):
            self.assertNotIn(pattern, text,
                             f'reintroduced raw interpolation: {pattern}')
        self.assertIn('escape(str(item[\'model_name\']), quote=True)', text)
        self.assertIn('escape(str(item[\'version_name\']), quote=True)', text)
        self.assertIn('escape(str(item[\'install_path\']), quote=True)', text)


def _load_global_module():
    """Import civitai_global with a stubbed WebUI opts object."""
    import importlib
    modules = types.ModuleType('modules')
    shared = types.ModuleType('modules.shared')
    shared.opts = types.SimpleNamespace(civitai_debug_prints=False)
    saved = {name: sys.modules.get(name) for name in ('modules', 'modules.shared')}
    sys.modules['modules'] = modules
    sys.modules['modules.shared'] = shared
    cwd = os.getcwd()
    try:
        sys.modules.pop('scripts.civitai_global', None)
        module = importlib.import_module('scripts.civitai_global')
        yield_module = module
    finally:
        os.chdir(cwd)
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return yield_module


class GlobalInitTests(unittest.TestCase):
    """init() must survive a fresh install where the config file does not exist."""

    def test_fresh_install_creates_subfolder_config(self):
        # Regression: the logging rewrite dropped "import json" while init() still
        # calls json.dump. That raised NameError on every fresh install, and
        # gl.init() runs at module level in four files, so the extension failed to
        # load at all. Existing installs never hit it because the file was already
        # there, which is exactly why it survived review.
        module = _load_global_module()
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            try:
                os.chdir(folder)
                module.init()
            finally:
                os.chdir(cwd)
            self.assertTrue(
                os.path.exists(os.path.join(folder, 'config_states',
                                           'civitai_subfolders.json')))

    def test_diagnostics_report_leaks_no_secret_values(self):
        module = _load_global_module()
        module.opts_shared = None
        # Re-point opts at values that must never appear in the report.
        shared = sys.modules.get('modules.shared')
        if shared is not None:
            shared.opts = types.SimpleNamespace(
                civitai_debug_prints=False, show_log=True,
                civitai_api_key='SECRET_KEY_abc123',
                some_unlisted_setting='UNLISTED_VALUE')
            module._debug_enabled = None
            with tempfile.TemporaryDirectory() as folder:
                cwd = os.getcwd()
                try:
                    os.chdir(folder)
                    module.init()
                    report = module.diagnostics_report(tail_lines=2)
                finally:
                    os.chdir(cwd)
            self.assertNotIn('SECRET_KEY_abc123', report)
            self.assertNotIn('UNLISTED_VALUE', report)
            self.assertIn('=== CivitAI Browser+ diagnostics ===', report)
