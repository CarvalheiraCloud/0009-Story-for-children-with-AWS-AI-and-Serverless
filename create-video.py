import subprocess, boto3, os, re, random

def limpar_srt(caminho_srt):
    if not os.path.exists(caminho_srt): return
    try:
        with open(caminho_srt, 'r', encoding='utf-8') as f:
            content = f.read()
        content_clean = re.sub(r'<[^>]+>', '', content).replace("'", "")
        with open(caminho_srt, 'w', encoding='utf-8') as f:
            f.write(content_clean)
    except: pass

def lambda_handler(event, context):
    s3 = boto3.client('s3')
    bucket_name = "carvalheira.cloud"
    h_id = str(event.get('historia_id', '')).strip()
    
    # 1. ESCOLHER MÚSICA ALEATÓRIA
    musica_p = "/tmp/bg_music.mp3"
    tem_musica = False
    try:
        num_musica = random.randint(1, 6)
        musica_key = f"story-musics/Little_Footsteps_{num_musica:02d}.mp3"
        s3.download_file(bucket_name, musica_key, musica_p)
        tem_musica = True
    except: pass

    prefixo = f"{h_id}/"
    response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefixo)
    if 'Contents' not in response: return {"status": "erro", "msg": "Pasta vazia"}

    def extrair_num(n): 
        nums = re.findall(r'\d+', n)
        return int(nums[0]) if nums else 0

    keys = [obj['Key'] for obj in response['Contents']]
    imagens = sorted([k for k in keys if k.lower().endswith('.jpg')], key=extrair_num)
    audios = sorted([k for k in keys if k.lower().endswith('.mp3')], key=extrair_num)
    legendas = sorted([k for k in keys if k.lower().endswith('.srt')], key=extrair_num)

    count = min(len(imagens), len(audios))
    lista_videos = []

    # 2. Processar capítulos (APENAS IMAGEM + VOZ)
    for i in range(count):
        img_p, aud_p, srt_p, cap_p = f"/tmp/v_{i}.jpg", f"/tmp/a_{i}.mp3", f"/tmp/s_{i}.srt", f"/tmp/cap_{i}.ts"
        s3.download_file(bucket_name, imagens[i], img_p)
        s3.download_file(bucket_name, audios[i], aud_p)
        
        v_filter = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1"
        if i < len(legendas):
            s3.download_file(bucket_name, legendas[i], srt_p)
            limpar_srt(srt_p)
            style = "FontSize=26,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Alignment=2,Fontname=Montserrat"
            v_filter += f",subtitles='{srt_p.replace(':', '\\:')}':fontsdir=/opt/fonts:force_style='{style}'"

        # Aqui geramos o vídeo SEM música ainda
        cmd_cap = [
            "/opt/bin/ffmpeg", "-loop", "1", "-i", img_p, "-i", aud_p,
            "-filter_complex", f"[0:v]{v_filter}[v]",
            "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "superfast", "-c:a", "aac", "-shortest", cap_p, "-y"
        ]
        subprocess.run(cmd_cap, check=True)
        lista_videos.append(f"file '{cap_p}'")

    # 3. Concatenar capítulos em um vídeo temporário sem trilha
    concat_file = "/tmp/concat.txt"
    video_sem_trilha = "/tmp/sem_trilha.mp4"
    with open(concat_file, "w") as f: f.write("\n".join(lista_videos))
    
    cmd_concat = ["/opt/bin/ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", video_sem_trilha, "-y"]
    subprocess.run(cmd_concat, check=True)

    # 4. MIXAGEM FINAL (Vídeo Completo + Trilha Sonora Contínua)
    output_path = f"/tmp/{h_id}_final.mp4"
    if tem_musica:
        # -stream_loop -1 faz a música repetir se o vídeo for maior
        # amix junta o áudio do vídeo original com a trilha baixinha
        cmd_final = [
            "/opt/bin/ffmpeg", "-i", video_sem_trilha, 
            "-stream_loop", "-1", "-i", musica_p,
            "-filter_complex", "[1:a]volume=0.10[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-y", output_path
        ]
        subprocess.run(cmd_final, check=True)
    else:
        os.rename(video_sem_trilha, output_path)

    # 5. Upload
    video_key = f"videos/{h_id}.mp4"
    s3.upload_file(output_path, bucket_name, video_key, ExtraArgs={'ContentType': 'video/mp4'})
    
    return {"status": "sucesso", "video_url": f"https://{bucket_name}://{video_key}"}
