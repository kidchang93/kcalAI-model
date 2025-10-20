from transformers import pipeline

from schemas.gpt_schemas import GptAnswer, GptResponse

# model_id="openai/gpt-oss-20b"
model_id="meta-llama/Meta-Llama-3.1-8B-Instruct"

pipe=pipeline(
    "text-generation",
    model=model_id,
    # torch_dtype="auto",
    device=-1,
)

def answerByGptOss20B(request: GptAnswer) -> GptResponse :
    # gpt_oss_20B 모델을 이용해 텍스트 응답 생성
    try:
        outputs=pipe(
            request.text,
            max_new_tokens=request.max_tokens,
        )

        # 출력에서 모델의 텍스트 부분 추출
        generated_text = outputs[0]["generated_text"]

        if isinstance(generated_text, list):
            generated_text = generated_text[-1]
        # 정제된 응답 반환
        return GptResponse(response_text=generated_text.strip())
    except Exception as e:
        raise RuntimeError(f"Model inference failed: {e}")

