import requests
import gradio as gr
import time
import shlex
import subprocess
import threading
import os
import re
import random
import platform
import stat
import json
import time
from pathlib import Path
from modules.shared import opts, cmd_opts
from scripts.civitai_global import print, debug_print
import scripts.civitai_global as gl
import scripts.civitai_api as _api
import scripts.civitai_file_manage as _file
from scripts.civitai_storage import enough_space, read_json, write_json
try:
    from zip_unicode import ZipHandler
except ImportError:
    print("Python module 'ZipUnicode' has not been imported correctly, please try to restart or install it manually.")
    
total_count = 0
current_count = 0
dl_manager_count = 0

def random_number(prev=None):
    number = str(random.randint(10000, 99999))
    while number == prev:
        number = str(random.randint(10000, 99999))
    
    return number

gl.init()
rpc_secret = "R7T5P2Q9K6"
try:
    queue = not cmd_opts.no_gradio_queue
except AttributeError:
    queue = not cmd_opts.disable_queue
except:
    queue = True

def start_aria2_rpc():
    start_file = os.path.join(aria2path, '_')
    running_file = os.path.join(aria2path, 'running')

    if os.path.exists(running_file):
        try:
            if os_type == 'Linux':
                env = os.environ.copy()
                env['PATH'] = '/usr/bin:' + env['PATH']
                subprocess.Popen(stop_rpc, env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(stop_rpc, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        except Exception as e:
            print(f"Failed to stop Aria2 RPC : {e}")
    else:
        if os.path.exists(start_file):
            os.rename(start_file, running_file)
            return
        else:
            with open(start_file, 'w', encoding="utf-8"):
                pass

    try:
        show_log = getattr(opts, "show_log", False)
        aria2_flags = getattr(opts, "aria2_flags", "")
        # Argument list instead of a shell string: aria2_flags is a free-text
        # setting and was interpolated into "shell=True" command, so anything like
        # "aria2_flags = '; rm -rf ~'" executed. The RPC is only ever reached via
        # http://localhost:24000 below, so it is not bound to every interface either.
        args = [aria2, '--enable-rpc', '--rpc-listen-port=24000',
                f'--rpc-secret={rpc_secret}', '--check-certificate=false',
                '--ca-certificate= ', '--file-allocation=none']
        if aria2_flags:
            args.extend(shlex.split(aria2_flags))
        subprocess_args = {'stdin': subprocess.DEVNULL}
        if not show_log:
            subprocess_args.update({'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL})
        else:
            subprocess_args.update({'stdout': None, 'stderr': None})

        subprocess.Popen(args, **subprocess_args)
        if os.path.exists(running_file):
            print("Aria2 RPC restarted")
        else:
            print("Aria2 RPC started")
    except Exception as e:
        print(f"Failed to start Aria2 RPC server: {e}")
        
aria2path = Path(__file__).resolve().parents[1] / "aria2"
os_type = platform.system()

if os_type == 'Windows':
    aria2 = os.path.join(aria2path, 'win', 'aria2.exe')
    stop_rpc = ['taskkill', '/im', 'aria2.exe', '/f']
    start_aria2_rpc()
elif os_type == 'Linux':
    aria2 = os.path.join(aria2path, 'lin', 'aria2')
    # Previously a bare os.stat at import time: a missing or unreadable binary made
    # the whole extension fail to import. Degrade to a logged RPC error instead.
    if os.path.exists(aria2):
        st = os.stat(aria2)
        os.chmod(aria2, st.st_mode | stat.S_IEXEC)
    stop_rpc = ['pkill', 'aria2']
    start_aria2_rpc()

class TimeOutFunction(Exception):
    pass

def create_model_item(dl_url, model_filename, install_path, model_name, version_name, model_sha256, model_id, create_json, from_batch=False, source_json=None):
    global dl_manager_count
    if model_id:
        model_id = int(model_id)
    if model_sha256:
        model_sha256 = model_sha256.upper()
    if model_sha256 == "UNKNOWN":
        model_sha256 = None
    if any(item['dl_url'] == dl_url for item in gl.download_queue):
        return None
    
    filtered_items = []
    size_bytes = 0
    version_id = None
    
    for item in (source_json or gl.json_data)['items']:
        if int(item['id']) == int(model_id):
            filtered_items.append(item)
            content_type = item['type']
            desc = item['description']
            main_folder = _api.contenttype_folder(content_type, desc)
            for version in item.get('modelVersions', []):
                for model_file in version.get('files', []):
                    if model_file.get('downloadUrl') == dl_url:
                        size_bytes = int(float(model_file.get('sizeKB') or 0) * 1024)
                        version_id = version.get('id')
            break
    
    sub_folder = os.path.normpath(os.path.relpath(install_path, main_folder))
    
    model_json = {"items": filtered_items}
    if from_batch:
        model_versions = None
        preview_value = ''
        existing_value = install_path
    else:
        model_versions = _api.update_model_versions(model_id)
        (preview_html,_,_,_,_,_,_,_,_,_,_,existing_path,_) = _api.update_model_info(None, model_versions.get('value'), False, model_id)
        preview_value = preview_html['value']
        existing_value = existing_path['value']
    
    dl_manager_count += 1
    
    item = {
        "dl_id": dl_manager_count,
        "dl_url" : dl_url,
        "model_filename" : model_filename,
        "install_path" : install_path,
        "model_name" : model_name,
        "version_name" : version_name,
        "model_sha256" : model_sha256,
        "model_id" : model_id,
        "create_json" : create_json,
        "model_json" : model_json,
        "model_versions" : model_versions,
        "preview_html" : preview_value,
        "existing_path": existing_value,
        "from_batch" : from_batch,
        "sub_folder" : sub_folder,
        "size_bytes": size_bytes,
        "version_id": version_id
    }
    
    return item

def selected_to_queue(model_list, subfolder, download_start, create_json, current_html, source_json=None):
    global total_count, current_count
    if gl.download_queue:
        number = download_start
    else:
        number = random_number(download_start)
        total_count = 0
        current_count = 0
        
    model_list = json.loads(model_list)

    for model_string in model_list:
        model_name, model_id = _api.extract_model_info(model_string)
        for item in (source_json or gl.json_data)['items']:
            if int(item['id']) == int(model_id):
                model_id, desc, content_type = item['id'], item['description'], item['type']
                versions = item.get('modelVersions', [])
                preferred_id = getattr(gl, 'update_preferred_versions', {}).get(str(model_id))
                version = next((v for v in versions if v.get('id') == preferred_id), versions[0] if versions else None)
                if not version or not version.get('files'):
                    break
                version_name = version.get('name')
                version_id = version.get('id')
                output_basemodel = version.get('baseModel') or ''
                nsfw = item.get('nsfw', False)
                model_uploader = (item.get('creator') or {}).get('username', '')
                files = version.get('files', [])
                primary_file = next((file for file in files if file.get('primary', False)), None)
                if primary_file:
                    model_filename = _api.cleaned_name(primary_file.get('name'))
                    model_sha256 = primary_file.get('hashes', {}).get('SHA256')
                    dl_url = primary_file.get('downloadUrl')
                else:
                    model_filename = _api.cleaned_name(files[0].get('name'))
                    model_sha256 = files[0].get('hashes', {}).get('SHA256')
                    dl_url = files[0].get('downloadUrl')
                break
        else:
            continue
        if not version or not version.get('files'):
            continue

        model_folder = _api.contenttype_folder(content_type, desc)
            
        default_subfolder = _api.sub_folder_value(content_type, desc)
        if default_subfolder != "None":
            default_subfolder = _file.convertCustomFolder(default_subfolder, output_basemodel, nsfw, model_uploader, model_name, model_id, version_name, version_id)

        if subfolder and subfolder != "None" and subfolder != "Only available if the selected files are of the same model type":
            from_batch = False
            if platform.system() == "Windows":
                subfolder = re.sub(r'[/:*?"<>|]', '', subfolder)
            
            if not subfolder.startswith(os.sep):
                subfolder = os.sep + subfolder
            install_path = model_folder + subfolder
        else:
            from_batch = True
            if default_subfolder != "None":
                install_path = model_folder + default_subfolder
            else:
                install_path = model_folder
        
        model_item = create_model_item(dl_url, model_filename, install_path, model_name, version_name, model_sha256, model_id, create_json, from_batch, source_json)
        if model_item:
            gl.download_queue.append(model_item)
            total_count += 1
    
    html = download_manager_html(current_html)

    return  (
            gr.Button.update(interactive=False, visible=False), # Download Button
            gr.Button.update(interactive=True, visible=True), # Cancel Button
            gr.Button.update(interactive=True if len(gl.download_queue) > 1 else False, visible=True), # Cancel All Button
            gr.Textbox.update(value=number), # Download Start Trigger
            gr.HTML.update(value='<div style="min-height: 100px;"></div>'), # Download Progress
            gr.HTML.update(value=html) # Download Manager HTML
    )


def queue_all_updates(download_start, create_json, current_html):
    """Queue every result from the completed update scan, including later pages."""
    items = list(getattr(gl, 'update_items', []))
    if not items:
        return (gr.Button.update(), gr.Button.update(), gr.Button.update(),
                gr.Textbox.update(value=download_start),
                gr.HTML.update(value='<div>Run the update scan first.</div>'),
                gr.HTML.update(value=current_html))
    names = [f"{item['name']} ({item['id']})" for item in items]
    return selected_to_queue(json.dumps(names), None, download_start, create_json,
                             current_html, {'items': items})


def gr_progress_threadable():
    """
    Gradio progress bars can no longer be updated from a separate thread, 
    so we need to use this to update them from the main thread.
    """
    
    # Gradio 3 does not need a wrapper
    if not hasattr(gr, "__version__") or int(gr.__version__.split(".")[0]) <= 3:
        return gr.Progress()
    
    gr_progress=gr.Progress()
    value = [0, None, False] # progress, desc, has_update

    def progress(p, desc=None):
        value[0] = p
        value[1] = desc
        value[2] = True

    def _update_progress():
        if value[2]:
            gr_progress(value[0], desc=value[1])
            value[2] = False
    
    def join(thread):
        _update_progress()
        while thread.is_alive():
            thread.join(timeout=0.1)
            _update_progress()

    progress.join = join
    
    return progress

    
def download_start(download_start, dl_url, model_filename, install_path, model_string, version_name, model_sha256, model_id, create_json, current_html):
    global total_count, current_count
    if model_string:
        model_name, _ = _api.extract_model_info(model_string)
    model_item = create_model_item(dl_url, model_filename, install_path, model_name, version_name, model_sha256, model_id, create_json)
    if model_item is None:
        return (gr.Button.update(), gr.Button.update(), gr.Button.update(),
                gr.Textbox.update(value=download_start), gr.HTML.update(),
                gr.HTML.update(value=download_manager_html(current_html)))

    gl.download_queue.append(model_item)
    
    if len(gl.download_queue) > 1:
        number = download_start
        total_count += 1
    else: 
        number = random_number(download_start)
        total_count = 1
        current_count = 0
    
    html = download_manager_html(current_html)

    return  (
            gr.Button.update(interactive=False, visible=True), # Download Button
            gr.Button.update(interactive=True, visible=True), # Cancel Button
            gr.Button.update(interactive=True if len(gl.download_queue) > 1 else False, visible=True), # Cancel All Button
            gr.Textbox.update(value=number), # Download Start Trigger
            gr.HTML.update(value='<div style="min-height: 100px;"></div>'), # Download Progress
            gr.HTML.update(value=html) # Download Manager HTML
    )

def download_finish(model_filename, version, model_id):
    if model_id:
        model_id = int(model_id)
        model_versions = _api.update_model_versions(model_id)
    else:
        model_versions = None
    if model_versions:
        version_choices = model_versions.get('choices', [])
    else:
        version_choices = []
    prev_version = gl.last_version + " [Installed]"
    
    if prev_version in version_choices:
        version = prev_version
        Del = True
        Down = False
    else:
        Del = False
        Down = True
        
    if gl.cancel_status:
        Del = False
        Down = True
    
    gl.download_fail = False
    gl.cancel_status = False
    
    return  (
            gr.Button.update(interactive=model_filename, visible=Down, value="Download model"), # Download Button
            gr.Button.update(interactive=False, visible=False), # Cancel Button
            gr.Button.update(interactive=False, visible=False), # Cancel All Button
            gr.Button.update(interactive=Del, visible=Del), # Delete Button
            gr.HTML.update(value='<div style="min-height: 0px;"></div>'), # Download Progress
            gr.Dropdown.update(value=version, choices=version_choices) # Version Dropdown
    )

CANCEL_WAIT_LIMIT = 1200


def await_download_stop(limit=None):
    """Poll until gl.isDownloading clears, bounded so a stuck downloader cannot block forever."""
    if limit is None:
        limit = CANCEL_WAIT_LIMIT
    for _ in range(limit):
        if not gl.isDownloading:
            return True
        time.sleep(0.5)
    return not gl.isDownloading


def download_cancel():
    gl.cancel_status = True
    gl.download_fail = True
    if gl.download_queue:
        item = gl.download_queue[0]
    else:
        item = None

    if await_download_stop():
        if item:
            model_string = f"{item['model_name']} ({item['model_id']})"
            _file.delete_model(0, item['model_filename'], model_string, item['version_name'], False, model_ver=item['model_versions'], model_json=item['model_json'])
    else:
        print(f"Download of \"{item['model_filename'] if item else 'model'}\" is still running; the cancel request was recorded but cleanup is deferred.")
    return

def download_cancel_all():
    gl.cancel_status = True
    gl.download_fail = True

    if gl.download_queue:
        item = gl.download_queue[0]
    else:
        item = None

    if await_download_stop():
        if item:
            model_string = f"{item['model_name']} ({item['model_id']})"
            _file.delete_model(0, item['model_filename'], model_string, item['version_name'], False, model_ver=item['model_versions'], model_json=item['model_json'])
        gl.download_queue = []
    else:
        print("Downloads are still running; the cancel request was recorded but cleanup is deferred.")
    return

def convert_size(size):
    for unit in ['bytes', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"

def get_download_link(url, model_id):
    headers = _api.get_headers(model_id)
    proxies, ssl = _api.get_proxies()
            
    response = requests.get(url, headers=headers, allow_redirects=False, timeout=(10, 30), proxies=proxies, verify=ssl)
    
    if 300 <= response.status_code <= 308:
        if "login?returnUrl" in response.text and "reason=download-auth" in response.text:
            return "NO_API"
        
        download_link = response.headers["Location"]
        return download_link
    else:
        return None

def download_file(url, file_path, install_path, model_id, progress=gr.Progress() if queue else None):
    # Derived before the try block: the failure handler below must never depend on a
    # local that only gets assigned once the request setup already succeeded.
    file_name = os.path.basename(file_path)
    final_path = os.path.join(install_path, file_name.removesuffix('.civitai-part'))
    try:
        disable_dns = getattr(opts, "disable_dns", False)
        split_aria2 = getattr(opts, "split_aria2", 64)
        max_retries = 5
        gl.download_fail = False
        aria2_rpc_url = "http://localhost:24000/jsonrpc"

        download_link = get_download_link(url, model_id)
        if not download_link:
            print(f'File: "{file_name}" not found on CivitAI servers, it looks like the file is not available for download.')
            gl.download_fail = True
            return
        
        elif download_link == "NO_API":
            print(f'File: "{file_name}" requires a personal CivitAI API to be downloaded, you can set your own API key in the CivitAI Browser+ settings in the SD-WebUI settings tab')
            gl.download_fail = "NO_API"
            if progress != None:
                progress(0, desc=f'File: "{file_name}" requires a personal CivitAI API to be downloaded, you can set your own API key in the CivitAI Browser+ settings in the SD-WebUI settings tab')
            return
        
        if disable_dns:
            dns = "false"
        else:
            dns = "true"
        
        options = {
            "dir": install_path,
            "max-connection-per-server": str(f"{split_aria2}"),
            "split": str(f"{split_aria2}"),
            "async-dns": dns,
            "continue": "true",
            "out": file_name
        }
        
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "aria2.addUri",
            "params": ["token:" + rpc_secret, [download_link], options]
        })
        
        try:
            response = requests.post(aria2_rpc_url, data=payload, timeout=10)
            data = json.loads(response.text)
            if 'result' not in data:
                raise ValueError(f'Failed to start download: {data}')
            gid = data['result']
        except Exception as e:
            print(f"Failed to start download: {e}")
            gl.download_fail = True
            return
            
        # Adaptive polling: a fixed 0.25s means four aria2 RPC calls per download
        # per second, which adds up across a queue. Poll fast while bytes arrive,
        # then ease off up to a second when nothing is moving.
        poll_interval = 0.25
        last_completed = -1
        while True:
            if gl.cancel_status:
                payload = json.dumps({
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "aria2.remove",
                    "params": ["token:" + rpc_secret, gid]
                })
                requests.post(aria2_rpc_url, data=payload, timeout=10)
                if progress != None:
                    progress(0, desc=f"Download cancelled.")
                return

            try:
                payload = json.dumps({
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "aria2.tellStatus",
                    "params": ["token:" + rpc_secret, gid]
                })
                
                response = requests.post(aria2_rpc_url, data=payload, timeout=10)
                status_info = json.loads(response.text)['result']
                
                total_length = int(status_info['totalLength'])
                completed_length = int(status_info['completedLength'])
                download_speed = int(status_info['downloadSpeed'])
                
                progress_percent = (completed_length / total_length) * 100 if total_length else 0
                
                remaining_size = total_length - completed_length
                if download_speed > 0:
                    eta_seconds = remaining_size / download_speed
                    eta_formatted = time.strftime("%H:%M:%S", time.gmtime(eta_seconds))
                else:
                    eta_formatted = "XX:XX:XX"
                if progress != None:
                    progress(progress_percent / 100, desc=f"Downloading: {file_name} - {convert_size(completed_length)}/{convert_size(total_length)} - Speed: {convert_size(download_speed)}/s - ETA: {eta_formatted} - Queue: {current_count}/{total_count}")
                
                if status_info['status'] == 'complete':
                    # aria2 wrote the .civitai-part file; the caller renames it to the
                    # final name, so report that path instead of the transfer path.
                    print(f"Model saved to: {final_path}")
                    if progress != None:
                        progress(1, desc=f"Model saved to: {final_path}")
                    gl.download_fail = False
                    return
                
                if status_info['status'] == 'error':
                    if progress != None:
                        progress(0, desc=f"Encountered an error during download of: \"{file_name}\" Please try again.")
                    gl.download_fail = True
                    return
                    
                if completed_length != last_completed:
                    last_completed = completed_length
                    poll_interval = 0.25
                else:
                    poll_interval = min(poll_interval * 1.5, 1.0)
                time.sleep(poll_interval)

            except Exception as e:
                print(f"Error occurred during Aria2 status update: {e}")
                max_retries -= 1
                if max_retries == 0:
                    if progress != None:
                        progress(0, desc=f"Encountered an error during download of: \"{file_name}\" Please try again.")
                    gl.download_fail = True
                    return
                time.sleep(5)
    except Exception as error:
        print(f"Download failed for {file_name}: {error}")
        if progress != None:
            progress(0, desc=f"Encountered an error during download of: \"{file_name}\" Please try again.")
        gl.download_fail = True

def info_to_json(install_path, model_id, model_sha256, unpackList=None, version_id=None):
    json_file = os.path.splitext(install_path)[0] + ".json"
    data = read_json(json_file, {})

    data['modelId'] = model_id
    if version_id is not None:
        data['modelVersionId'] = version_id
    if model_sha256:
        data['sha256'] = model_sha256
    if unpackList:
        data['unpackList'] = unpackList

    write_json(json_file, data)

def download_file_old(url, file_path, model_id, progress=gr.Progress() if queue else None):
    try:
        gl.download_fail = False
        max_retries = 5
        downloaded_size = 0
        tokens = re.split(re.escape(os.sep), file_path)
        file_name_display = tokens[-1].removesuffix('.civitai-part')
        start_time = time.time()
        last_update_time = 0
        update_interval = 0.25
        
        download_link = get_download_link(url, model_id)
        if not download_link:
            print(f'File: "{file_name_display}" not found on CivitAI servers, it looks like the file is not available for download.')
            if progress != None:
                progress(0, desc=f'File: "{file_name_display}" not found on CivitAI servers, it looks like the file is not available for download.')
            gl.download_fail = True
            return
        
        elif download_link == "NO_API":
            print(f'File: "{file_name_display}" requires a personal CivitAI API key to be downloaded, you can set your own API key in the CivitAI Browser+ settings in the SD-WebUI settings tab')
            gl.download_fail = "NO_API"
            if progress != None:
                progress(0, desc=f'File: "{file_name_display}" requires a personal CivitAI API key to be downloaded, you can set your own API key in the CivitAI Browser+ settings in the SD-WebUI settings tab')
            return
        
        headers = _api.get_headers(model_id, True)
        proxies, ssl = _api.get_proxies()
        
        while True:
            if gl.cancel_status:
                if progress != None:
                    progress(0, desc=f"Download cancelled.")
                return
            if os.path.exists(file_path):
                downloaded_size = os.path.getsize(file_path)
                headers['Range'] = f"bytes={downloaded_size}-"
            else:
                downloaded_size = 0
                headers.pop('Range', None)
                
            with open(file_path, "ab") as f:
                while gl.isDownloading:
                    try:
                        if gl.cancel_status:
                            if progress != None:
                                progress(0, desc=f"Download cancelled.")
                            return
                        try:
                            if gl.cancel_status:
                                if progress != None:
                                    progress(0, desc=f"Download cancelled.")
                                return
                            response = requests.get(download_link, headers=headers, stream=True, timeout=(10, 60), proxies=proxies, verify=ssl)
                            if response.status_code == 404:
                                if progress != None:
                                    progress(0, desc=f"Encountered an error during download of: {file_name_display}, file is not found on CivitAI servers.")
                                gl.download_fail = True
                                return
                            response.raise_for_status()
                            if downloaded_size and response.status_code == 200:
                                f.seek(0)
                                f.truncate()
                                downloaded_size = 0
                            total_size = int(response.headers.get("Content-Length", 0)) + downloaded_size
                        except Exception:
                            raise TimeOutFunction("Timed Out")

                        if total_size == 0:
                            total_size = downloaded_size

                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                if gl.cancel_status:
                                    if progress != None:
                                        progress(0, desc=f"Download cancelled.")
                                    response.close()
                                    return
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                elapsed_time = time.time() - start_time
                                download_speed = downloaded_size / elapsed_time
                                remaining_size = total_size - downloaded_size
                                if download_speed > 0:
                                    eta_seconds = remaining_size / download_speed
                                    eta_formatted = time.strftime("%H:%M:%S", time.gmtime(eta_seconds))
                                else:
                                    eta_formatted = "XX:XX:XX"
                                current_time = time.time()
                                if current_time - last_update_time >= update_interval:
                                    if progress != None:
                                        progress(downloaded_size / total_size if total_size else 0, desc=f"Downloading: {file_name_display} {convert_size(downloaded_size)} / {convert_size(total_size)} - Speed: {convert_size(int(download_speed))}/s - ETA: {eta_formatted} - Queue: {current_count}/{total_count}")
                                    last_update_time = current_time
                                if gl.isDownloading == False:
                                    response.close()
                                    break
                        response.close()
                        downloaded_size = os.path.getsize(file_path)
                        break

                    except TimeOutFunction:
                        if progress != None:
                            progress(0, desc="CivitAI API did not respond, retrying...")
                        max_retries -= 1
                        if max_retries == 0:
                            if progress != None:
                                progress(0, desc=f"Encountered an error during download of: {file_name_display}, please try again.")
                            gl.download_fail = True
                            return
                        time.sleep(5)

            if (gl.isDownloading == False):
                break

            gl.isDownloading = False
            downloaded_size = os.path.getsize(file_path)
            if downloaded_size >= total_size:
                if not gl.cancel_status:
                    print(f"Model saved to: {file_path}")
                    if progress != None:
                        progress(1, desc=f"Model saved to: {file_path}")
                    gl.download_fail = False
                    return

            else:
                if progress != None:
                    progress(0, desc=f"Encountered an error during download of: {file_name_display}, please try again.")
                print(f"File download failed: {file_name_display}")
                gl.download_fail = True
    except Exception as error:
        print(f"Standard download failed for {file_name_display}: {error}")
        if progress != None:
            progress(0, desc=f"Encountered an error during download of: {file_name_display}, please try again.")
        gl.download_fail = True

def download_create_thread(download_finish, queue_trigger, progress=gr_progress_threadable() if queue else None):
    global current_count
    current_count += 1
    if not gl.download_queue:
        return  (
            gr.HTML.update(), # Download Progress HTML
            gr.Textbox.update(value=None), # Current Model
            gr.Textbox.update(value=random_number(download_finish)), # Download Finish Trigger
            gr.Textbox.update(value=queue_trigger), # Queue Trigger
            gr.Button.update(interactive=False) # Cancel All Button
    )
    item = gl.download_queue[0]
    gl.cancel_status = False
    use_aria2 = getattr(opts, "use_aria2", True)
    unpack_zip = getattr(opts, "unpack_zip", False)
    save_all_images = getattr(opts, "auto_save_all_img", False)
    gl.recent_model = item['model_name']
    gl.last_version = item['version_name']
        
    if item['from_batch']:
        item['model_versions'] = _api.update_model_versions(item['model_id'], item['model_json'])
        preview_result = _api.update_model_info(None, item['version_name'], False,
                                                item['model_id'], item['model_json'],
                                                version_id=item.get('version_id'))
        item['preview_html'] = preview_result[0]['value']
        item['existing_path'] = preview_result[11]['value'] or item['install_path']
        item['install_path'] = item['existing_path']
        
    card_name = None
    try:
        gl.isDownloading = True
        _file.make_dir(item['install_path'])
        
        path_to_new_file = os.path.join(item['install_path'], item['model_filename'])
        transfer_path = path_to_new_file + '.civitai-part'
    
        enough, free_bytes = enough_space(item['install_path'], item.get('size_bytes', 0))
        if not enough:
            print(f"Not enough free disk space for {item['model_filename']}: {convert_size(free_bytes)} free, {convert_size(item.get('size_bytes', 0))} required plus 512 MB reserve.")
            gl.download_fail = True
        else:
            if use_aria2 and os_type != 'Darwin':
                thread = threading.Thread(target=download_file, args=(item['dl_url'], transfer_path, item['install_path'], item['model_id'], progress))
            else:
                thread = threading.Thread(target=download_file_old, args=(item['dl_url'], transfer_path, item['model_id'], progress))
            thread.start()
            if progress is not None and hasattr(progress, "join"):
                progress.join(thread)
            else:
                thread.join()
            if use_aria2 and os_type != 'Darwin' and gl.download_fail is True and not gl.cancel_status:
                print(f"Aria2 failed for {item['model_filename']}; retrying with the standard downloader.")
                gl.download_fail = False
                fallback = threading.Thread(target=download_file_old,
                                            args=(item['dl_url'], transfer_path, item['model_id'], progress))
                fallback.start()
                if progress is not None and hasattr(progress, "join"):
                    progress.join(fallback)
                else:
                    fallback.join()
            if not gl.download_fail and not gl.cancel_status:
                try:
                    if not os.path.exists(transfer_path):
                        raise FileNotFoundError(transfer_path)
                    os.replace(transfer_path, path_to_new_file)
                    _api.invalidate_inventory()
                except OSError as error:
                    print(f"Failed to finish download of {item['model_filename']}: {error}")
                    gl.download_fail = True
    
        if not gl.cancel_status and not gl.download_fail:
            if os.path.exists(path_to_new_file):
                unpackList = []
                if unpack_zip:
                    try:
                        if path_to_new_file.endswith('.zip'):
                            directory = Path(os.path.dirname(path_to_new_file))
                            zip_handler = ZipHandler(path_to_new_file)
                        
                            for _, decoded_name in zip_handler.name_map.items():
                                unpackList.append(decoded_name)
                        
                            zip_handler.extract_all(directory)
                            zip_handler.zip_ref.close()
                        
                            print(f"Successfully extracted {item['model_filename']} to {directory}")
                            os.remove(path_to_new_file)
                    except ImportError:
                        print("Python module 'ZipUnicode' has not been imported correctly, cannot extract zip file. Please try to restart or install it manually.")
                    except Exception as e:
                        print(f"Failed to extract {item['model_filename']} with error: {e}")
                if not gl.cancel_status:
                    if item['create_json']:
                        _file.save_model_info(item['install_path'], item['model_filename'], item['sub_folder'], item['model_sha256'], item['preview_html'], api_response=item['model_json'])
                    info_to_json(path_to_new_file, item['model_id'], item['model_sha256'], unpackList, item.get('version_id'))
                    _api.invalidate_inventory()
                    _file.save_preview(path_to_new_file, item['model_json'], True, item['model_sha256'])
                    if save_all_images:
                        _file.save_images(item['preview_html'], item['model_filename'], item['install_path'], item['sub_folder'], api_response=item['model_json'])
                
        if gl.download_fail:
            if gl.cancel_status:
                print(f'Cancelled download of "{item["model_filename"]}"')
            else:
                if not gl.download_fail == "NO_API":
                    print(f'Error occured during download of "{item["model_filename"]}"')
    
        if gl.cancel_status:
            card_name = None
        else:
            model_string = f"{item['model_name']} ({item['model_id']})"
            (card_name, _, _) = _file.card_update(item['model_versions'], model_string, item['version_name'], True)
    
    except Exception as error:
        # Any failure below used to escape before the queue was popped, which left
        # the finished item at gl.download_queue[0] and gl.isDownloading stuck on
        # True. Every later download then saw a non-empty queue and refused to
        # start, so the tool stopped downloading entirely.
        print(f"Failed to process queued download of \"{item.get('model_filename', 'unknown model')}\": {error}")
        gl.download_fail = True
    finally:
        if gl.download_queue and gl.download_queue[0] is item:
            gl.download_queue.pop(0)
        gl.isDownloading = False

    
    if len(gl.download_queue) == 0:
        finish_nr = random_number(download_finish)
        queue_nr = queue_trigger
    else:
        finish_nr = download_finish
        queue_nr = random_number(queue_trigger)
        
    return  (
            gr.HTML.update(), # Download Progress HTML
            gr.Textbox.update(value=card_name), # Current Model
            gr.Textbox.update(value=finish_nr), # Download Finish Trigger
            gr.Textbox.update(value=queue_nr), # Queue Trigger
            gr.Button.update(interactive=True if len(gl.download_queue) > 1 else False) # Cancel All Button
    )

def remove_from_queue(dl_id):
    global total_count
    for item in gl.download_queue:
        if int(dl_id) == int(item['dl_id']):
            gl.download_queue.remove(item)
            total_count -= 1
            return

def arrange_queue(input):
    id_and_index = input.split('.')
    dl_id = int(id_and_index[0])
    index = int(id_and_index[1]) + 1
    for item in gl.download_queue:
        if int(item['dl_id']) == dl_id:
            current_item = gl.download_queue.pop(gl.download_queue.index(item))
            gl.download_queue.insert(index, current_item)
            break
    
def get_style(size, left_border):
    return f"flex-grow: {size};" + ("border-left: 1px solid var(--border-color-primary);" if left_border else "") + "padding: 5px 10px 5px 10px;width: 0;align-self: center;"

def download_manager_html(current_html):
    html = current_html.rsplit("</div>", 1)[0]
    pattern = r'dl_id="(\d+)"'
    matches = re.findall(pattern, html)
    existing_item_ids = [int(match) for match in matches]
    
    for item in gl.download_queue:
        if not item['dl_id'] in existing_item_ids:
            download_item = f'''
                <div class="civitai_dl_item" dl_id="{item['dl_id']}" style="display: flex; font-size: var(--section-header-text-size);">
                <div class="dl_name" style="{get_style(1, False)}"><span title="{item['model_name']}">{item['model_name']}</span></div>
                <div class="dl_ver" style="{get_style(0.75, True)}"><span title="{item['version_name']}">{item['version_name']}</span></div>
                <div class="dl_path" style="{get_style(1.5, True)}"><span title="{item['install_path']}">{item['install_path']}</span></div>
                <div class="dl_stat" style="{get_style(1.5, True)}"><div class="dl_progress_bar" style="width:0%">In queue...</div></div>
                <div class="dl_action_btn" style="{get_style(0.3, True)}text-align: center;"><span onclick="removeDlItem({item['dl_id']}, this)" class="civitai-btn-text" style="font-size: larger;">Remove</span></div>
                </div>
                '''
            html = html + download_item
    
    html = html + "</div>"
    
    return html
