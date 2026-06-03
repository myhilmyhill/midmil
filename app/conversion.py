import asyncio
import os
from datetime import datetime

ALSA_DEVICE = "hw:Em28xxAudio"
MIDI_PORT = "24:0"
process_lock = asyncio.Lock()

def get_midi_reset_data() -> bytes:
    # GM System Reset SysEx: F0 7E 7F 09 01 F7
    # All Sound Off (CC 120), Reset All Controllers (CC 121), All Notes Off (CC 123) for channels 0-15
    track_data = bytearray()
    track_data.extend(b'\x00\xF0\x05\x7E\x7F\x09\x01\xF7')
    for chan in range(16):
        track_data.extend(bytes([0, 0xB0 + chan, 120, 0]))
        track_data.extend(bytes([0, 0xB0 + chan, 121, 0]))
        track_data.extend(bytes([0, 0xB0 + chan, 123, 0]))
    track_data.extend(b'\x00\xFF\x2F\x00')
    header = b'MThd\x00\x00\x00\x06\x00\x00\x00\x01\x00\x80'
    track_header = b'MTrk' + len(track_data).to_bytes(4, 'big')
    return header + track_header + track_data

async def run_conversion(midi_path: str, wav_path: str):
    async with process_lock:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] 変換開始: {midi_path}")
        
        # 録音開始前にMIDIリセットメッセージ（全ノートOFF、コントローラーリセット、GMリセット）を送信
        try:
            reset_data = get_midi_reset_data()
            reset_proc = await asyncio.create_subprocess_exec(
                "aplaymidi", "-p", MIDI_PORT, "/dev/stdin",
                stdin=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, reset_stderr = await reset_proc.communicate(input=reset_data)
            if reset_proc.returncode != 0:
                print(f"aplaymidi reset failed with code {reset_proc.returncode}, stderr: {reset_stderr.decode().strip()}")
            # 音源側のリセット処理時間を考慮して少し待つ
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"MIDI reset failed to send: {e}")
        
        temp_wav_path = wav_path + ".tmp"
        record_proc = await asyncio.create_subprocess_exec(
            "arecord", "-D", ALSA_DEVICE, "-f", "S16_LE", "-c", "2", "-r", "48000", "-t", "wav", temp_wav_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 録音プロセス（arecord）が開始し、ALSAデバイスが初期化されるのを2秒待つ
        # （一部のUSBキャプチャカードは、録音開始時にハードウェアミキサーが自動的にミュート状態にリセットされるため）
        await asyncio.sleep(1)

        # arecord がすでに終了しているかチェック（即座にクラッシュしたか）
        if record_proc.returncode is not None:
            record_stdout, record_stderr = await record_proc.communicate()
            print(f"arecord failed immediately with code {record_proc.returncode}, stdout: {record_stdout.decode().strip()}, stderr: {record_stderr.decode().strip()}")
            if os.path.exists(temp_wav_path):
                try:
                    os.remove(temp_wav_path)
                except Exception as e:
                    print(f"Failed to clean up temp file {temp_wav_path}: {e}")
            return

        # 録音開始後にミキサーのミュート解除と音量調整を実行
        mixer_cmds = [
            ["amixer", "-c", "Em28xxAudio", "cset", "name=Line In Switch", "on"],
            ["amixer", "-c", "Em28xxAudio", "cset", "name=Line In Volume", "80%"],
            ["amixer", "-c", "Em28xxAudio", "cset", "name=Master Switch", "on"],
            ["amixer", "-c", "Em28xxAudio", "cset", "name=PCM Switch", "on"],
            ["amixer", "-c", "Em28xxAudio", "cset", "name=Line Switch", "on"]
        ]
        for cmd in mixer_cmds:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                     print(f"mixer setup error for {cmd}: exit {proc.returncode}, stderr: {stderr.decode().strip()}")
            except Exception as e:
                print(f"mixer setup exception for {cmd}: {e}")

        # MIDI再生を開始
        play_proc = await asyncio.create_subprocess_exec(
            "aplaymidi", "-p", MIDI_PORT, midi_path,
            stderr=asyncio.subprocess.PIPE
        )
        
        _, play_stderr = await play_proc.communicate()
        if play_proc.returncode != 0:
            print(f"aplaymidi failed with code {play_proc.returncode}, stderr: {play_stderr.decode().strip()}")
        
        record_proc.terminate()
        record_stdout, record_stderr = await record_proc.communicate()
        # 1, -15 or 143 usually means terminated by SIGTERM/SIGINT, which is expected/normal for arecord
        if record_proc.returncode not in (0, 1, -15, 143):
            print(f"arecord failed with code {record_proc.returncode}, stdout: {record_stdout.decode().strip()}, stderr: {record_stderr.decode().strip()}")
        
        # 録音完了後に一時ファイルを最終出力先にリネーム
        try:
            if os.path.exists(temp_wav_path):
                os.rename(temp_wav_path, wav_path)
            else:
                print(f"Temporary file {temp_wav_path} not found, cannot rename to {wav_path}")
        except Exception as e:
            print(f"Failed to rename {temp_wav_path} to {wav_path}: {e}")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] 変換完了: {wav_path}")
