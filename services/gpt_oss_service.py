import os

import torch
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from transformers import pipeline

from schemas.gpt_schemas import GptAnswer, GptResponse

# model_id="openai/gpt-oss-20b"
# model_id="meta-llama/Llama-3.2-1B-Instruct"
# model_id="skt/ko-gpt-trinity-1.2B-v0.5"
# local_model="D:/lck_data/git_data/ko-gpt-trinity-1.2B-v0.5"
# dotenv 로 환경변수 불러오기
load_dotenv()
token=os.environ.get("HF_TOKEN")

# pipe=pipeline(
#     "text-generation",
#     model=local_model,
#     # token=token,
#     device=-1,
# )
client=InferenceClient(
    provider="groq",
    api_key=os.environ["HF_TOKEN"]
)

def answerByGptOss20B(request: GptAnswer) -> GptResponse :
    # gpt_oss_20B 모델을 이용해 텍스트 응답 생성
    try:
        # outputs=pipe(
        #     request.text,
        #     max_new_tokens=request.max_tokens,
        # )
        #
        # # 출력에서 모델의 텍스트 부분 추출
        # generated_text = outputs[0]["generated_text"]
        #
        # if isinstance(generated_text, list):
        #     generated_text = generated_text[-1]

        # 정제된 응답 반환
        # return GptResponse(response_text=generated_text.strip())

        #API 방식
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "user",
                    "content": request.text
                }
            ],
            max_tokens=request.max_tokens
        )

        # 모델 출력 텍스트 추출
        generated_text = completion.choices[0].message["content"]

        # 정제 후 반환
        return GptResponse(response_text=generated_text.strip())
    except Exception as e:
        raise RuntimeError(f"Model inference failed: {e}")

