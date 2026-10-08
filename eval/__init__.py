"""분류 정확도 평가 (docs/agent-prompt.md 5장 · README 3-5).

python -m eval            정답이 달린 예시 대화를 가닥에 흘려보내고, 가닥이 붙인 값과 견줘 숫자 넷을 내요
python -m eval.agree      둘이 따로 단 정답이 서로 얼마나 맞는지 (정답 자체를 믿을 수 있는지)

정답 파일(data/example_conversations.json)은 실제 대화라 공개 저장소에 없어요. 팀 내부 링크에서 받아 같은
자리에 두고, 커밋하지 마요. 정답 파일이 없어도 만든 예시로는 돌려 볼 수 있어요: python -m eval --demo
"""
