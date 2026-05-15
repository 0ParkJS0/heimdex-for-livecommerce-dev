# 라이브커머스 AI 쇼츠 리디자인 — 세션 인계 문서

> **목적**: 본 세션 토큰 한도 도달 시 다른 Claude 계정으로 작업 인계용. 이 문서 전체를 복붙해서 새 세션에 붙여넣으면 동일 컨텍스트로 이어갈 수 있음.
>
> **마지막 갱신**: 2026-05-15 (Phase 0 완료, Phase 1 시작 직전)

---

## 0. 즉시 알아야 할 것

- **작업 경로**: `/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev/services/web`
- **저장소**: heimdex-for-livecommerce-dev (Heimdex 조직, branch=main)
- **커밋 규칙**: ⚠️ **Co-Authored-By Claude 절대 금지** (Heimdex 저장소 정책)
- **커밋 단위**: **마이크로 커밋** — 컴포넌트 1개 또는 토큰 1세트 단위로 작게 자주
- **푸시 금지**: git push는 사용자 명시 승인 필수, 자동 푸시 금지
- **백엔드 변경 0건**: 프론트엔드만 작업. 내보내기 백엔드 API는 미정이므로 mock/stub
- **로컬 테스트 우선**: 지석님이 `npm run dev` 직접 실행. claude는 dev 서버 호출 금지(토큰 절약)
- **언어**: 한국어로 응답 (코드 식별자/기술용어는 원어 유지)

---

## 1. 프로젝트 컨텍스트

### 1.1 무엇을 하는가
Heimdex 라이브커머스 제품의 AI 쇼츠 생성 flow + 내 쇼츠 페이지를 Figma `P3 - Marketing` 디자인(fileKey `PYDMMAvFq7PmhjyVTftiU6`)에 맞춰 리디자인.

### 1.2 핵심 노드 ID (Figma)
| 화면 | 노드 ID |
|---|---|
| 동영상 상세 / 개요 탭 | 1713:270773 |
| Wizard - 옵션 설정 | 1713:288216 |
| Wizard - 상품 선택 (single) | 1713:288149 |
| Wizard - 상품 선택 (multi) | 1713:288182 |
| Wizard - 인덱싱 진행 | 1713:288103 |
| Wizard - 결과 | 1713:288042 |
| 내 쇼츠 (저장된 쇼츠 목록) | 1713:287987 |
| 생성 취소 Dialog | 1602:36895 |
| 편집 페이지 (Phase 5, 후속) | 1713:271669, 274802, 275432, 275817, 275105 |

### 1.3 스택
- Next.js 14.1 (App Router) + React 18 + TypeScript 5.3
- Tailwind 3.4 (디자인 토큰 확장 완료)
- lucide-react 1.16
- Vitest 4.0
- Auth0 (Auth0 enabled 시) / Dev login (NEXT_PUBLIC_AUTH0_ENABLED=false 시)

---

## 2. Phase 0 — 완료된 작업 (검증됨)

### 2.1 디자인 토큰 (tailwind.config.ts:11-82)
- `heimdex-navy.{400,500,600,700}` (#496a94 ~ #1a3d61), primary=500=#234c77
- `grayscale.{10,100,200,300,400,500,800}` (#fcfcff ~ #272833)
- `neutral-h.{50~800}`, `red-h.{50,400,500}`, `green-h.{50,400,500}`, `amber-h.{50,500}`
- `boxShadow.card` = `0px 4px 20px 0px rgba(232,233,248,1)`
- `boxShadow.dialog` = `2px 2px 20px 0px rgba(0,0,0,0.25)`
- `borderRadius.card` = 10px, `borderRadius.dialog` = 20px
- 폰트: Pretendard (`var(--font-pretendard)`)

### 2.2 신규 컴포넌트 (Phase 0)
**아이콘** (`src/components/icons/figma/`):
- `HeimdexBrand.tsx`, `HeimdexSymbol.tsx`, `HeimdexWordmark.tsx`
- `WarningIcon.tsx`, `TooltipArrow.tsx`
- `index.ts` (re-export)

**공통 UI** (`src/components/ui/`):
- `Button.tsx` (primary/secondary/ghost × sm/md)
- `Snackbar.tsx` (bottom-center | top-right)
- `Stepper.tsx` (3-step indicator)
- `Dialog.tsx` (확인 다이얼로그)
- `Popover.tsx` (⋮ 메뉴)
- `figma-index.ts` (re-export)

**자산**: `public/figma-assets/icons/` 에 SVG 복사 완료

**레이아웃**: `Sidebar.tsx`, `TopHeader.tsx` 의 로고/토글만 신규 자산으로 교체. 메뉴 구조는 유지.

### 2.3 검증 상태
- `npm run type-check` exit 0 (3회)
- 기존 vitest 60+ 테스트 회귀 통과
- dev 서버 실행 확인은 지석님 직접

---

## 3. Phase 1 — 동영상 상세 / 개요 탭 (현재 작업 시작점)

### 3.1 파일
- 대상: `src/app/videos/[videoId]/page.tsx`
- 관련 컴포넌트: `src/features/videos/`, `src/features/preedit/` (탭 영역)

### 3.2 디자인 매핑 (1713:270773)
- **좌측 동영상 카드** (341px 폭)
  - 썸네일 + 컨트롤 + 메타데이터: 파일 위치/폴더/재생 시간/업로드 일자
- **우측 탭 영역**
  - 탭: 개요 / 장면 분석 / 인물 관리
  - 우상단: "AI 쇼츠 생성" 버튼 (primary navy/500) + "장면 재분석" 버튼 (secondary)
- **개요 탭 본문**
  - 행동 요약 카드
  - 스크립트: 화자 A = `text-red-h-400`, 화자 B = `text-green-h-400`
  - 메시지 = 타임스탬프 (00:00:02) + 텍스트 + 복사 아이콘
- **인터랙션**
  - "AI 쇼츠 생성" 클릭 → 우측 영역만 `InlineWizardContainer`로 swap (left 동영상 카드는 유지)

### 3.3 작업 순서
1. `src/app/videos/[videoId]/page.tsx` Read → 현재 구조 파악
2. 좌측 동영상 카드 컴포넌트 디자인 적용
3. 우측 탭 헤더 + AI 쇼츠 생성/장면 재분석 버튼 적용
4. 개요 탭: 행동 요약 + 스크립트 (화자 색 구분)
5. type-check → 마이크로 커밋

---

## 4. Phase 2 — Inline Wizard

### 4.1 파일
- `src/features/shorts-auto-product-wizard/components/InlineWizardContainer.tsx`
- `InlineWizardCriteriaPanel.tsx` (1713:288216)
- `InlineWizardProductPanel.tsx` (1713:288149, 288182)
- 신규: `IndexingProgressPanel.tsx` (1713:288103)

### 4.2 Stepper (1713:288216 상단)
- 3-step: `1.옵션 설정 → 2.상품 선택 → 3.AI 쇼츠 생성`
- active = navy/500 원 + 검정 텍스트, inactive = `neutral-h.300` 원 + 회색 텍스트
- 구분자 = `chevron-right` (24px, lucide)
- 마운트 위치: GNB 아래, 컨텐츠 위 (디자인 좌표 top:28px)

### 4.3 InlineWizardCriteriaPanel 리디자인 (1713:288216)
- 카드 폭 578px, padding 20, gap 60
- 헤더: "옵션 설정" + 우측 "다음" 버튼 (primary navy)
- **생성 유형 카드 2개** (single / multi 토글)
- **영상 구간** 슬라이더: 양끝 핸들 + tooltip (왼=시작, 오=종료)
- **쇼츠 길이** 5개 카드: 15 / 30 / 60 / 90 / 120
- **쇼츠 개수** 10개 카드: 1~10 + 동적 안내 칩 (예: "15:40 영상에서 60초 쇼츠라면 5~7개가 적합")
- **LanguageToggle 제거** (디자인에 없음)

### 4.4 InlineWizardProductPanel 리디자인 (1713:288149/288182)
- 상단: 옵션 요약 칩 + "다음" 버튼 (모든 상태 표시, ready=활성)
- 안내 박스 (single/multi 분기):
  - single: "선택한 상품을 모두 포함한 쇼츠 N개를 생성합니다."
  - multi: "선택한 상품마다 하나씩, 별도의 쇼츠 N개를 생성합니다. 상품은 최대 4개까지 선택 가능합니다."
- 그리드: `flex flex-wrap justify-between gap-y-[20px]`, 카드 200×200
- 카드 보더: 1px `grayscale.100` / 선택 시 2px `heimdex-navy.500`, 체크박스 우상단
- Cap 분기: single=4개 고정, multi=`requested_count`
- Cap 초과 시 `Snackbar` (하단 중앙): "최대 N개까지 선택할 수 있어요 / 적게 고르면 나머지는 AI가 자동으로 채워줘요"
- 다음 클릭 → `/export/shorts/auto/wizard/{videoId}/result/{parentJobId}` push (현행 유지)

### 4.5 IndexingProgressPanel 신규 (1713:288103)
- 4단계 파이프라인 칩 (queued / current / completed):
  - 한국어 라벨: "동영상 분석" / "상품 인식" / "장면 조립" / "렌더링"
  - 백엔드 ScanStage 매핑: enumerating → tracking → assembling → rendering
- 현재 단계: navy/500 보더 + 스피너 + 진행 텍스트
- 완료 단계: navy/600 배경 + 흰 체크
- 큰 38% 텍스트 (navy/500) + "약 40초 남았습니다" (계산: 잔여 children × 평균 렌더 시간)
- 상단: 옵션 요약 칩 + 비활성 다음 버튼
- 마운트 조건: result 페이지에서 `children_total === 0` 또는 어떤 child도 `render_status === "completed"` 아닐 때

---

## 5. Phase 3 — 결과 화면 (1713:288042)

### 5.1 파일
- `WizardStepResult.tsx` (또는 `src/app/export/shorts/auto/wizard/[videoId]/result/[parentJobId]/page.tsx`)
- `src/features/shorts-auto-product-wizard/components/ExportShortsButton.tsx`

### 5.2 디자인
- **헤더**: "생성된 쇼츠 N개" + "모두 저장하기" (secondary) + "모두 내보내기" (primary navy)
- **카드 4상태** (ScanStage + render_status 조합):
  - 대기 중: stage ∈ {queued, enumerating, tracking} → gray 칩
  - 생성 중: stage ∈ {assembling, rendering} OR render_status=rendering → `amber-h` (#ffefda 배경 / #e07f00 텍스트) 칩
  - 완료: render_status=completed → `green-h.50` 배경 / `green-h.500` 텍스트 칩
  - 실패: stage ∈ {failed, cancelled} → `red-h.50` / `red-h.500` 칩
- **카드 구조** (287×253):
  - 좌 썸네일 150×253 + 좌하단 상품 태그 (1개 또는 2개+)
    - 상품 태그 산출: `criteria.product_distribution` + `selected catalog_entry_ids`
  - 우 메타: 제목 / 길이 / 진행률 / 캡션(`RenderJobResponse.summary` 50자 truncate) / 상태 칩
  - 우상단: ⋮ 메뉴 Popover
- **메뉴 분기**:
  - 진행률 < 100%: 제목 변경 / 생성 취소(red)
  - 진행률 = 100%: 제목 변경 / 저장하기 / 내보내기 / 생성 취소(red)
- **생성 취소** 클릭 → 확인 Dialog (디자인 1602:36895 문구 적용)

---

## 6. Phase 4 — 내 쇼츠 페이지 (1713:287987)

### 6.1 파일
- `src/app/shorts/page.tsx` 또는 `src/features/shorts/SavedShortsPage.tsx`

### 6.2 디자인
- **헤더**: "저장된 쇼츠 목록 N개" + "새 쇼츠 생성" (secondary + plus 아이콘) + "내보내기" (primary navy)
- **검색바**: lucide `Search` + placeholder "찾고 싶은 영상을 제목으로 검색해보세요."
- **정렬 드롭다운**: "생성 일자 순" + chevron-down
- **카드 그리드**: 9:16 (200×337 + 라벨 영역)
- **페이지네이션**: double-left / left / 숫자 / right / double-right (디자인 그대로)

### 6.3 Export 진행 Snackbar
- `useExportBatch` 훅의 `exportState` Map watch
- 진행 중인 batch 있으면 우상단 토스트
- 내용: 스피너 + "쇼츠 저장 중" + "X% · 남은 시간" + X 닫기
- 진행률: `completed / total` (Map status=completed 카운트). 남은 시간 = 평균 렌더 속도 기반
- ⚠️ 내보내기 백엔드 미정 → `// NOTE(export-backend-tbd):` 주석으로 wiring 지점 표시

---

## 7. 확정 결정사항 (지석님 2026-05-15)

1. 기존 코드 검토 후 적용 — `features/shorts-auto-product-wizard/` 광범위 구현, 새로 만들지 말 것
2. Tailwind theme.colors 확장 + CSS 변수 병행 (Phase 0 완료)
3. AI 쇼츠 생성 flow 먼저(Phase 1-4), 편집 페이지 후속(Phase 5+)
4. 백엔드 변경 0건 (이미 디자인과 1:1 매칭)
5. `InlineWizardContainer` 기반 리디자인 (풀스크린 `WizardLayout` 대신)
6. 로고/사이드바 토글만 자산 교체
7. lucide-react 패키지 사용 (커스텀 = 로고/Warning/TooltipArrow만 inline SVG)
8. 결과 화면 4상태 = ScanStage + render_status 조합 (백엔드 변경 없음)
9. 내보내기 백엔드 미정 → 프론트만 Figma대로 mock 구성
10. 결과 카드: 100% 미만 메뉴 ⋮ = 2개(제목/취소), 100% = 4개. 좌하단 상품 태그 + 우측 캡션 50자 truncate. 생성 취소 dialog = 1602:36895 패턴

---

## 8. 인증 우회 (preview용)

### 8.1 현재 상태
- `src/components/layout/AppLayout.tsx` 에서 미인증 시 `/login` redirect
- `NO_LAYOUT_ROUTES = ["/login", "/auth/"]` 만 우회 가능
- 환경변수 `NEXT_PUBLIC_AUTH0_ENABLED=false` 면 dev login으로 전환되나 여전히 토큰 필요

### 8.2 권장 방안 (지석님께 제안)
**옵션 A: dev login으로 1회 로그인** (가장 빠름)
- `.env.local` 에 `NEXT_PUBLIC_AUTH0_ENABLED=false` 설정
- `npm run dev` → `localhost:3000` → /login 화면에서 dev 계정 입력
- 세션이 남아있는 동안 모든 페이지 접근 가능

**옵션 B: `/preview` 라우트 추가** (Phase 후 추가 작업)
- `AppLayout.tsx` `NO_LAYOUT_ROUTES` 에 `/preview` 추가
- `src/app/preview/[...slug]/page.tsx` 로 mock 데이터 주입하는 wrapper 페이지 작성
- ⚠️ 사이드바/헤더 없어짐 → 디자인 검수 용도라면 OK

→ 지석님 선택 대기

### 8.3 페이지별 URL (인증 후)
| 페이지 | URL |
|---|---|
| 동영상 목록 | `/videos` |
| 동영상 상세 / 개요 (Phase 1) | `/videos/[videoId]` |
| AI 쇼츠 Wizard - 옵션 (Phase 2) | `/export/shorts/auto/wizard/[videoId]/criteria` |
| AI 쇼츠 Wizard - 상품 선택 (Phase 2) | `/export/shorts/auto/wizard/[videoId]/select-product` |
| AI 쇼츠 Wizard - 결과 (Phase 3) | `/export/shorts/auto/wizard/[videoId]/result/[parentJobId]` |
| 내 쇼츠 (Phase 4) | `/shorts` |

---

## 9. 검증 정책 (지석님 요구)

- 기능 개발 = **로컬 테스트 → EC2 검증 → PR** 순서 필수
- `npm run dev` 은 **지석님 직접** 실행 (claude 호출 금지)
- 기존 vitest 60+ 테스트 회귀 통과 유지
- 백엔드 변경 시 계획 공유 → 승인 후 실행
- Heimdex 저장소 커밋 = **Co-Authored-By Claude 금지**
- 커밋 = 마이크로 단위 (컴포넌트 1개 / 토큰 1세트)
- 푸시 = 명시적 승인 필수

---

## 10. 새 세션 시작 시 체크리스트

새 Claude에게 인계할 때 다음 순서로 진행:

1. 이 HANDOFF.md 전체 복붙
2. 새 세션에서 다음 명령 실행:
   ```bash
   cd "/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev/services/web"
   git status
   git log --oneline -10
   ```
3. Phase 1 시작점: `src/app/videos/[videoId]/page.tsx` Read
4. Figma 노드 fetch (1713:270773) — 새 세션에서 figma MCP `get_design_context` 호출
5. 마이크로 커밋으로 진행 (Co-Authored-By 금지 재확인)

---

## 11. 마지막 커밋 / 진행 상태

본 문서 작성 시점에서 진행 중:
- **현재 Phase**: Phase 1 시작 직전 (`src/app/videos/[videoId]/page.tsx` 미독)
- **마지막 검증된 상태**: Phase 0 (`type-check exit 0` × 3회, vitest pass)
- **다음 단계**: `src/app/videos/[videoId]/page.tsx` Read → 디자인 매칭 → 컴포넌트 분리 → 커밋

---

## 12. 메모리 참조 (~/.claude-company/projects/-mnt-c-...-LEVEL-UP/memory/)

다음 파일이 자동 로드되어 있음 (새 세션에도 동일):
- `project_livecommerce_redesign.md` — 10개 결정사항 + Phase 로드맵
- `project_livecommerce_export_pending.md` — 내보내기 백엔드 미정 정책
- `feedback_commit_style.md` — Co-Authored-By 금지
- `feedback_local_test_first.md` — 로컬 → EC2 → PR 순서
- `feedback_no_push_without_approval.md` — 푸시 승인 필수
- `feedback_plan_before_server_changes.md` — 서버 변경 시 계획 공유
- `feedback_ai_coding_principles.md` — matklad 원칙 (경계는 직접, 구현만 위임)
