import asyncio
import os

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

async def run_conversion(midi_path: str, output_path: str):
    async with process_lock:
        print(f"変換開始: {midi_path}")
        
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
        
        temp_flac_path = output_path + ".tmp"
        
        record_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "alsa", "-channels", "2", "-sample_rate", "48000", "-i", ALSA_DEVICE, "-c:a", "flac", "-f", "flac", temp_flac_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 録音プロセス（ffmpeg）が開始し、ALSAデバイスが初期化されるのを1秒待つ
        # （一部のUSBキャプチャカードは、録音開始時にハードウェアミキサーが自動的にミュート状態にリセットされるため）
        await asyncio.sleep(1)

        # ffmpeg がすでに終了しているかチェック（即座にクラッシュしたか）
        if record_proc.returncode is not None:
            record_stdout, record_stderr = await record_proc.communicate()
            print(f"ffmpeg recording failed immediately with code {record_proc.returncode}, stdout: {record_stdout.decode().strip()}, stderr: {record_stderr.decode().strip()}")
            if os.path.exists(temp_flac_path):
                try:
                    os.remove(temp_flac_path)
                except Exception as e:
                    print(f"Failed to clean up temp file {temp_flac_path}: {e}")
            return

        # 録音開始後にミキサーのミュート解除と音量調整を実行
        mixer_cmds = [
            ["amixer", "-D", ALSA_DEVICE, "cset", "name=Line In Switch", "on"],
            ["amixer", "-D", ALSA_DEVICE, "cset", "name=Line In Volume", "50%"],
        ]
        for cmd in mixer_cmds:
            for attempt in range(5):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await proc.communicate()
                    if proc.returncode == 0:
                        break
                    else:
                        err_msg = stderr.decode().strip()
                        print(f"mixer setup attempt {attempt + 1} failed for {cmd}: exit {proc.returncode}, stderr: {err_msg}")
                        if attempt < 4:
                            await asyncio.sleep(1.0)
                except Exception as e:
                    print(f"mixer setup exception for {cmd} on attempt {attempt + 1}: {e}")
                    if attempt < 4:
                        await asyncio.sleep(1.0)

        # MIDI再生を開始
        play_proc = await asyncio.create_subprocess_exec(
            "aplaymidi", "-p", MIDI_PORT, midi_path,
            stderr=asyncio.subprocess.PIPE
        )
        
        _, play_stderr = await play_proc.communicate()
        if play_proc.returncode != 0:
            print(f"aplaymidi failed with code {play_proc.returncode}, stderr: {play_stderr.decode().strip()}")
        
        try:
            record_proc.terminate()
        except ProcessLookupError:
            pass
        record_stdout, record_stderr = await record_proc.communicate()
        # If the file exists and is not empty, we consider it a success,
        # but we still print a warning if the returncode is unexpected.
        is_success = False
        if os.path.exists(temp_flac_path) and os.path.getsize(temp_flac_path) > 0:
            is_success = True
            if record_proc.returncode not in (0, 1, -15, 255, -255, 143):
                print(f"ffmpeg recording finished with unexpected code {record_proc.returncode}, but output file exists. stdout: {record_stdout.decode().strip()}, stderr: {record_stderr.decode().strip()}")
        else:
            print(f"ffmpeg recording failed with code {record_proc.returncode}. Output file missing or empty. stdout: {record_stdout.decode().strip()}, stderr: {record_stderr.decode().strip()}")

        if is_success:
            # Rename temp FLAC file to final path upon success
            try:
                abs_temp = os.path.abspath(temp_flac_path)
                abs_out = os.path.abspath(output_path)
                os.rename(abs_temp, abs_out)
                print(f"Successfully converted and saved: {abs_out}")
            except Exception as e:
                print(f"Failed to rename {temp_flac_path} to {output_path}: {e}")
        else:
            if os.path.exists(temp_flac_path):
                try:
                    os.remove(temp_flac_path)
                except Exception as e:
                    print(f"Failed to clean up incomplete FLAC file {temp_flac_path}: {e}")

        print(f"変換完了: {output_path}")
