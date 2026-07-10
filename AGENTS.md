# checkss 작업 규칙

## 버전 관리

- 제품 코드나 동작을 업데이트할 때마다 버전 숫자를 반드시 올린다.
- 현재 버전이 `1.1.0`이면 다음 업데이트는 최소 `1.1.1`로 저장한다.
- 다음 위치의 버전을 항상 동일하게 맞춘다.
  - `src/config.py`의 `APP_VERSION`
  - `installer/checkss.iss`의 `MyAppVersion`
  - `build-installer.ps1`의 설치 파일명
  - `README.md`의 설치 파일명과 버전 설명
- 새 설치 파일은 `release/checkss-Setup-<새 버전>.exe`로 빌드한다.
- 이전 버전 설치 파일을 새 결과로 덮어쓰지 않는다.
- 버전 변경과 관련 검증이 끝나기 전에는 업데이트 완료로 보고하지 않는다.
