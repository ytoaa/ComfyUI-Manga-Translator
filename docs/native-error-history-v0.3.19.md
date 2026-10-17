# v0.3.19 네이티브 큐 실패 진단과 중단 정책

18페이지가 모두 `execution_failed`, `failure_node=null`로 남은 보고에서 오류 수집 결함을 확인했다. 이 수정은 실패 원인을 보존하는 문제를 해결한다. 기존 18페이지의 실제 모델/노드 예외 원인까지 해당 보고만으로 확정하지 않는다.

## 원인

ComfyUI `PromptExecutor.add_message`는 `(event, data)` tuple을 저장한다. `PromptQueue.task_done`과 `get_history`의 Python 경로는 이 tuple을 유지한다. HTTP history JSON에서는 같은 항목이 list가 된다. 기존 프로젝트 수집기는 list만 허용해 네이티브 큐의 `execution_error` / `execution_interrupted`를 버렸다.

따라서 실제 예외 종류·메시지·실패 노드가 누락되고, 메모리·디스크·모델 구성·사용자 중지 오류의 프로젝트 일시정지 정책까지 적용되지 않을 수 있었다. 기존 HTTP 형태의 모의 응답은 이를 재현하지 못했다. [상류 구현](https://github.com/Comfy-Org/ComfyUI/blob/master/execution.py)의 `add_message`, `task_done`, `get_history` 계약을 확인했다.

## 변경

- tuple/list를 모두 읽고 예외 종류, 노드 종류/ID, 메시지, 이벤트 및 제한된 traceback을 시도별 state에 저장한다. summary에는 노드 ID와 메시지 앞부분도 표시한다.
- native/HTTP 모두 메모리·디스크·서비스·모델 구성·사용자 중지 실패에서 다음 페이지를 제출하지 않는다. 정상적으로 분류된 OCR/식자 품질 실패는 기존처럼 페이지별로 분리한다.
- 오류 status에 유효한 실패 정보가 없으면 명시적인 진단을 저장하고 프로젝트를 일시정지한다. 일반 재개로 이 상태를 조용히 건너뛰지 않는다.
- 이전 `execution_failed` 기록에 메시지가 비어 있으면 일반 재개 시 원래 prompt ID의 이력에서 진단을 복원한다. 진단 복원을 위해 새 prompt를 제출하지 않는다. 기존 이력이 없거나 모순되면 일시정지한다.
- 전체 실패 시 보고서에 성공한 페이지가 없고 `실패 재시도`가 필요함을 명시한다. `시작·재개`는 알려진 일반 실패 페이지를 재제출하지 않는다.

## 기존 프로젝트 확인

ComfyUI를 재시작하면 메모리의 prompt 이력이 사라질 수 있다. 업데이트 전에 살아 있는 history나 서버 예외 로그를 먼저 확보한다. 예를 들어 해당 보고의 첫 실패는 아래처럼 읽을 수 있다. 기본 포트가 다르면 주소를 바꾼다.

```bash
python3 - <<'PY'
import json
from urllib.request import urlopen
ident = 'e71315f5-9226-4a1d-874e-988b31c60303'
with urlopen('http://127.0.0.1:8188/history/' + ident, timeout=10) as response:
    history = json.load(response).get(ident)
if not history:
    print('해당 prompt 이력이 없습니다. 당시 ComfyUI 예외 로그가 필요합니다.')
else:
    status = history.get('status') or {}
    print('status:', status.get('status_str'), 'completed:', status.get('completed'))
    for event, data in status.get('messages', []):
        if event in ('execution_error', 'execution_interrupted'):
            print(json.dumps({k:data.get(k) for k in ('node_id','node_type','exception_type','exception_message','traceback')}, ensure_ascii=False, indent=2))
PY
```

보고에 있던 `attempt-000002`는 이전 두 번째 시도 기록이다. 부모 warmup/시작 확인 뒤 페이지 실행 로그 없이 바로 끝났다면, 기존 실패를 일반 재개에서 건너뛴 흐름과 일치한다. detector warmup 경고만으로 실제 페이지 실패 원인을 판단하지 않는다.

업데이트·재시작 후 새 모델 실행이 필요하면 같은 입력 노드의 `action=실패 재시도`로 실행한다. 이전 시도는 보존하고 새 시도를 추가한다. 자원·구성 문제는 원인을 해결한 뒤 재시도한다. 새로운 원인 불명 실패는 첫 페이지에서 멈추고 나머지는 제출하지 않는다.

## 검증

`tests/test_native_failure_history.py`는 실제 native adapter가 반환하는 tuple과 HTTP list에 대해 같은 정책을 검사한다. 품질 실패 계속 처리, 메모리/디스크/모델 누락/중지 시 다음 제출 0건, 오류 상세 누락 시 재개 차단, 이전 진단 복원, 이력 유실 시 명시적 재시도 및 이전 시도 보존을 포함한다. 실제 DGX 모델 추론은 별도 확인 범위다.
