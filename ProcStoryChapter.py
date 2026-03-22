import json
import boto3
import base64
import re

def ms_to_srt(ms):
    seconds = int((ms / 1000) % 60)
    minutes = int((ms / (1000 * 60)) % 60)
    hours = int((ms / (1000 * 60 * 60)) % 24)
    millis = int(ms % 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def lambda_handler(event, context):
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1') ## mude aqui ## 
    polly = boto3.client('polly', region_name='us-east-1') ## mude aqui ##
    s3 = boto3.client('s3')
    
    bucket_name = "carvalheira.cloud"  ## mude aqui ##
    h_id = event.get('historia_id', 'historia_padrao')
    cap_idx = event.get('capitulo_index', 0)
    prompt_image = event.get('prompt_image','blank image')
    
    # Texto original (com pontuação) vindo do n8n
    texto_orig = event.get('texto_ssml', 'Olá')
    texto_limpo = re.sub(r'<[^>]+>', '', texto_orig).strip()
    
    # Lista de todas as palavras do texto original COM pontuação
    palavras_originais = texto_limpo.split()
    
    # Texto ajustado para o Polly (85% de velocidade)
    texto_ssml_ajustado = f'<speak><prosody rate="85%">{texto_limpo}</prosody></speak>'

    # 1. ÁUDIO
    res_audio = polly.synthesize_speech(
        Text=texto_ssml_ajustado, OutputFormat='mp3', VoiceId='Justin', Engine='standard', TextType='ssml'  ## mude aqui ##
    )
    audio_key = f"{h_id}/audio_{cap_idx}.mp3"
    s3.put_object(Bucket=bucket_name, Key=audio_key, Body=res_audio['AudioStream'].read())

    # 2. LEGENDA (SRT) COM PONTUAÇÃO RECUPERADA
    res_marks = polly.synthesize_speech(
        Text=texto_ssml_ajustado, OutputFormat='json', SpeechMarkTypes=['word'], VoiceId='Justin', Engine='standard', TextType='ssml' ## mude aqui ##
    )
    
    marks_lines = res_marks['AudioStream'].read().decode('utf-8').splitlines()
    srt_content = ""
    
    palavras_bloco = []
    tempo_inicio_bloco = None
    indice_srt = 1
    MAX_PALAVRAS = 6

    for i, line in enumerate(marks_lines):
        mark = json.loads(line)
        if mark['type'] == 'word':
            if not palavras_bloco:
                tempo_inicio_bloco = mark['time']
            
            # Recupera a palavra com pontuação da nossa lista original
            # i corresponde ao índice da palavra atual
            if i < len(palavras_originais):
                palavra_com_ponto = palavras_originais[i]
            else:
                palavra_com_ponto = mark['value']
                
            palavras_bloco.append(palavra_com_ponto)
            
            if i + 1 < len(marks_lines):
                tempo_fim_bloco = json.loads(marks_lines[i+1])['time']
            else:
                tempo_fim_bloco = mark['time'] + 800

            if len(palavras_bloco) >= MAX_PALAVRAS or i == len(marks_lines) - 1:
                frase = " ".join(palavras_bloco)
                srt_content += f"{indice_srt}\n{ms_to_srt(tempo_inicio_bloco)} --> {ms_to_srt(tempo_fim_bloco)}\n{frase}\n\n"
                palavras_bloco = []
                indice_srt += 1

    srt_key = f"{h_id}/legenda_{cap_idx}.srt"
    s3.put_object(Bucket=bucket_name, Key=srt_key, Body=srt_content.encode('utf-8'), ContentType='text/plain; charset=utf-8')

    # 3. IMAGEM
    prompt_limpo_img = re.sub(r'<[^>]+>', '', prompt_image).strip()
    safe_prompt = f"Wholesome digital art for children, safe and friendly, storybook style: {prompt_limpo_img}"
    body_image = json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": safe_prompt},
        "imageGenerationConfig": {"numberOfImages": 1, "height": 768, "width": 1280, "cfgScale": 8.0}
    })
    
    ## mude aqui ##
    res_image = bedrock.invoke_model(body=body_image, modelId="amazon.titan-image-generator-v2:0", accept="application/json", contentType="application/json")
    res_body = json.loads(res_image.get("body").read())
    img_base64 = res_body.get("images")[0]
    img_key = f"{h_id}/imagem_{cap_idx}.jpg"
    s3.put_object(Bucket=bucket_name, Key=img_key, Body=base64.b64decode(img_base64), ContentType='image/jpeg')

    return {
        "status": "sucesso",
        "capitulo": cap_idx,
        "audio_key": audio_key,
        "image_key": img_key,
        "srt_key": srt_key
    }
