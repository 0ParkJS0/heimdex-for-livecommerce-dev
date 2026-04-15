import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import get_settings
from app.logging_config import setup_logging, get_logger
from app.modules.orgs.models import Org
from app.modules.users.models import User, UserRole
from app.modules.libraries.models import Library
from app.modules.profiles.models import LibraryProfile, ProfileStatus
from app.modules.people.models import DriveNicknameRegistry, PeopleClusterLabel
from app.modules.text_templates.models import TextTemplate
from app.modules.face.models import FaceIdentity, FaceExemplar
from app.modules.search.client import OpenSearchClient
from app.modules.search.scene_client import SceneSearchClient
from app.modules.search.embedding import generate_mock_embedding

setup_logging()
logger = get_logger(__name__)

KOREAN_TRANSCRIPTS = [
    "안녕하세요. 오늘 회의에서 논의할 주요 안건은 신규 프로젝트 일정입니다.",
    "이번 분기 매출 목표를 달성하기 위해 마케팅 전략을 수정해야 합니다.",
    "고객 피드백을 분석한 결과, 사용자 인터페이스 개선이 필요합니다.",
    "다음 주에 있을 제품 출시를 위해 최종 점검을 진행하겠습니다.",
    "팀 워크샵에서 새로운 아이디어들이 많이 나왔습니다.",
    "클라우드 인프라 마이그레이션 프로젝트가 성공적으로 완료되었습니다.",
    "인공지능 기반 추천 시스템 개발에 대해 설명드리겠습니다.",
    "보안 취약점 패치가 완료되어 시스템이 더 안전해졌습니다.",
    "사용자 경험을 개선하기 위한 A/B 테스트 결과를 공유합니다.",
    "데이터베이스 최적화로 쿼리 성능이 50% 향상되었습니다.",
    "모바일 앱 업데이트에 새로운 기능이 추가되었습니다.",
    "고객 지원 팀의 응답 시간이 크게 단축되었습니다.",
    "신규 파트너십 체결로 사업 확장의 기회가 생겼습니다.",
    "분기별 실적 보고서를 검토하고 있습니다.",
    "프로젝트 마일스톤 달성을 축하드립니다.",
    "기술 문서화 작업이 완료되어 온보딩이 수월해질 것입니다.",
    "서버 모니터링 시스템 구축이 완료되었습니다.",
    "코드 리뷰 프로세스 개선 방안을 논의하겠습니다.",
    "자동화 테스트 커버리지가 80%를 달성했습니다.",
    "다국어 지원 기능이 추가되어 글로벌 확장이 가능해졌습니다.",
    "머신러닝 모델 학습 파이프라인을 구축했습니다.",
    "스프린트 회고에서 도출된 개선점을 공유합니다.",
    "API 문서가 업데이트되어 개발자 경험이 향상되었습니다.",
    "성능 테스트 결과 목표치를 초과 달성했습니다.",
    "장애 대응 프로세스가 개선되어 복구 시간이 단축되었습니다.",
]

ENGLISH_TRANSCRIPTS = [
    "Welcome to today's presentation on quarterly results.",
    "Let's discuss the roadmap for the upcoming release.",
    "The customer satisfaction survey shows positive trends.",
    "We need to address the scalability concerns immediately.",
    "The new feature deployment was successful.",
    "Team collaboration has improved significantly this month.",
    "Security audit findings require immediate attention.",
    "The migration to the new platform is progressing well.",
    "User engagement metrics have exceeded expectations.",
    "Let's review the action items from yesterday's meeting.",
]

# Human-readable video titles for seed data (simulates agent-derived filenames)
KOREAN_VIDEO_TITLES = [
    "2025년 1분기 전사 회의",
    "신규 프로젝트 킥오프 미팅",
    "마케팅 전략 수정 회의",
    "고객 피드백 분석 결과 공유",
    "제품 출시 최종 점검",
    "팀 워크샵 아이디어 발표",
    "클라우드 마이그레이션 완료 보고",
    "AI 추천 시스템 기술 세미나",
    "보안 취약점 패치 리뷰",
    "UX 개선 A/B 테스트 결과",
    "데이터베이스 최적화 성과 발표",
    "모바일 앱 업데이트 데모",
    "고객지원 프로세스 개선 회의",
    "신규 파트너십 논의",
    "분기별 실적 보고",
]

ENGLISH_VIDEO_TITLES = [
    "Q1 2025 Quarterly Results Review",
    "Product Roadmap Planning Session",
    "Customer Satisfaction Deep Dive",
    "Scalability Workshop Part 1",
    "Feature Launch Retrospective",
    "Team Collaboration Best Practices",
    "Security Audit Findings Review",
    "Platform Migration Status Update",
    "User Engagement Analytics Demo",
    "Sprint Planning - Week 12",
    "Onboarding Training Session",
    "API Integration Workshop",
    "Performance Optimization Results",
    "Cross-Team Sync Meeting",
    "Year-End Review Presentation",
]

TRAINING_VIDEO_TITLES = [
    "New Employee Onboarding Guide",
    "Git Workflow Training",
    "Cloud Infrastructure Basics",
    "CI/CD Pipeline Setup Tutorial",
    "Code Review Best Practices",
    "Incident Response Playbook",
    "Data Privacy Compliance Training",
    "Agile Methodology Overview",
    "Kubernetes Deployment Training",
    "Monitoring and Alerting Setup",
]


# --- AI Tags Pool (전부 한국어, vocabulary.py 기준) ---

# 행동/상황 태그 (VLM_KEYWORD_TAGS 한국어 display name)
KEYWORD_TAGS_POOL = [
    "제품 시연", "제품 리뷰", "언박싱", "사용법/튜토리얼", "비교", "비포/애프터",
    "가격 공개", "할인/특가", "세트/구성 소개", "한정 수량/타임딜",
    "쿠폰/이벤트", "무료배송", "사은품 증정",
    "질문/답변", "시청자 요청", "실시간 반응", "경품 추첨",
    "클로즈업/디테일", "발색/테스트", "성분 설명", "제형/텍스처",
    "사이즈 비교", "패키징", "착용/착화", "조리/시식",
]

# 제품 카테고리 태그 (VLM_PRODUCT_TAGS 한국어 display name)
PRODUCT_TAGS_POOL = [
    "스킨케어", "메이크업", "헤어케어", "바디케어", "향수/프래그런스", "네일", "뷰티 디바이스",
    "의류", "신발", "가방", "액세서리/주얼리",
    "식품", "건강식품/영양제", "가전", "주방용품", "인테리어/리빙", "반려동물",
    "전자기기", "모바일 액세서리", "유아/아동",
]

# 구체적 제품명 풀 (자유 형식)
PRODUCT_ENTITIES_POOL = [
    "레티놀 세럼", "비타민C 앰플", "히알루론산 토너",
    "매트 립스틱", "글로우 쿠션", "아이섀도 팔레트",
    "다이슨 에어랩", "스타일러 고데기", "헤어 트리트먼트",
    "센텔리안24 마데카 크림", "고주파 뷰티 디바이스", "LED 마스크",
    "프리미엄 한우 세트", "건강즙 세트", "비타민 영양제",
    "무선 청소기", "에어프라이어", "커피 머신",
    "메디큐브 AGR", "클렌징 디바이스", "폼 클렌저", "클렌징 오일",
    "크린랩", "주방용 랩", "위생 랩",
]

# AI 자유 형식 한국어 태그 (VLM이 상황 보고 자유롭게 붙이는 태그)
AI_TAGS_POOL = [
    "신제품 언박싱", "성분 설명", "실사용 후기", "가격 비교",
    "한정판 출시", "베스트셀러 소개", "MD 추천템", "사은품 증정 이벤트",
    "피부 타입별 추천", "데일리 메이크업", "프리미엄 라인",
    "계절 한정", "시즌 오프", "선물용 추천",
    "인플루언서 협업", "브랜드 앰버서더",
]



async def seed_database():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session:
        existing = await session.execute(select(Org).where(Org.slug == "devorg"))
        if existing.scalar_one_or_none():
            logger.info("seed_already_exists", msg="Database already seeded")
            return
        
        logger.info("seeding_database")
        
        org = Org(
            slug="devorg",
            name="Development Organization",
            auth0_org_id="org_V0Y81197qiMgjFFX",
        )
        session.add(org)
        await session.flush()
        logger.info("created_org", org_id=str(org.id), slug=org.slug)
        
        admin = User(org_id=org.id, email="admin@devorg.example.com", role=UserRole.ADMIN)
        member = User(org_id=org.id, email="member@devorg.example.com", role=UserRole.MEMBER)
        session.add_all([admin, member])
        await session.flush()
        logger.info("created_users", count=2)
        
        libraries = [
            Library(org_id=org.id, name="회사 회의 영상", created_by_user_id=admin.id),
            Library(org_id=org.id, name="Product Demos", created_by_user_id=admin.id),
            Library(org_id=org.id, name="Training Videos", created_by_user_id=member.id),
        ]
        session.add_all(libraries)
        await session.flush()
        logger.info("created_libraries", count=len(libraries))
        
        profiles = []
        for lib in libraries:
            profile = LibraryProfile(
                org_id=org.id,
                library_id=lib.id,
                status=ProfileStatus.ACTIVE,
                activated_at=datetime.now(timezone.utc),
            )
            profiles.append(profile)
        session.add_all(profiles)
        await session.flush()
        logger.info("created_profiles", count=len(profiles))
        
        drive_entries = [
            DriveNicknameRegistry(
                org_id=org.id,
                source_fingerprint_hash="abc123def456",
                nickname="작업용 외장 하드",
            ),
            DriveNicknameRegistry(
                org_id=org.id,
                source_fingerprint_hash="xyz789uvw012",
                nickname="Backup Drive",
            ),
        ]
        session.add_all(drive_entries)
        await session.flush()
        logger.info("created_drive_nicknames", count=len(drive_entries))
        
        people_clusters = [
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_001", label="김철수"),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_002", label="이영희"),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_003", label="John Smith"),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_004", label=None),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_005", label=None),
        ]
        session.add_all(people_clusters)
        await session.flush()
        logger.info("created_people_clusters", count=len(people_clusters))

        await seed_text_templates(session, org.id)

        # Face용 video_id를 미리 생성 — seed_scenes()와 공유해서
        # FaceExemplar.video_id가 OpenSearch 장면 문서와 조인되도록 함
        face_video_ids = [str(uuid4()) for _ in range(7)]
        await seed_faces(session, org.id, face_video_ids)

        await session.commit()

        await seed_opensearch(org, libraries, profiles, people_clusters, drive_entries)
        await seed_scenes(org, libraries, profiles, people_clusters, drive_entries, face_video_ids)


SYSTEM_TEXT_PRESETS = [
    {
        "name": "기본",
        "font_family": "Noto Sans KR", "font_size_px": 48, "font_color": "#FFFFFF",
        "font_weight": 700, "line_height": 1.4, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.85,
        "shadow_enabled": True, "shadow_color": "#000000",
        "shadow_offset_x": 2, "shadow_offset_y": 2, "shadow_blur": 4,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
    {
        "name": "강조",
        "font_family": "Pretendard", "font_size_px": 64, "font_color": "#FFD700",
        "font_weight": 700, "line_height": 1.3, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.5,
        "shadow_enabled": True, "shadow_color": "#000000",
        "shadow_offset_x": 3, "shadow_offset_y": 3, "shadow_blur": 6,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
    {
        "name": "제품소개",
        "font_family": "Noto Sans KR", "font_size_px": 36, "font_color": "#FFFFFF",
        "font_weight": 400, "line_height": 1.5, "letter_spacing": 0,
        "text_align": "left", "position_x": 0.08, "position_y": 0.12,
        "shadow_enabled": False, "shadow_color": "#000000",
        "shadow_offset_x": 0, "shadow_offset_y": 0, "shadow_blur": 0,
        "background_enabled": True, "background_color": "#000000B3", "background_padding": 12,
    },
    {
        "name": "가격",
        "font_family": "Pretendard", "font_size_px": 56, "font_color": "#FF4444",
        "font_weight": 700, "line_height": 1.3, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.5,
        "shadow_enabled": True, "shadow_color": "#FFFFFF",
        "shadow_offset_x": 2, "shadow_offset_y": 2, "shadow_blur": 4,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
    {
        "name": "엔딩",
        "font_family": "Noto Sans KR", "font_size_px": 42, "font_color": "#FFFFFF",
        "font_weight": 700, "line_height": 1.4, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.5,
        "shadow_enabled": True, "shadow_color": "#000000",
        "shadow_offset_x": 3, "shadow_offset_y": 3, "shadow_blur": 8,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
]


async def seed_text_templates(session: AsyncSession, org_id) -> None:
    """시스템 프리셋 텍스트 템플릿 시딩. 이미 존재하는 이름은 건너뜀."""
    existing = await session.execute(
        select(TextTemplate).where(
            TextTemplate.org_id == org_id,
            TextTemplate.is_system_preset.is_(True),
        )
    )
    existing_names = {t.name for t in existing.scalars().all()}

    created = 0
    for preset in SYSTEM_TEXT_PRESETS:
        if preset["name"] in existing_names:
            continue
        template = TextTemplate(
            org_id=org_id,
            user_id=None,
            is_system_preset=True,
            **preset,
        )
        session.add(template)
        created += 1

    if created:
        await session.flush()
    logger.info("seeded_text_templates", created=created, skipped=len(existing_names))


async def seed_faces(session: AsyncSession, org_id, face_video_ids: list[str]) -> None:
    """얼굴 임베딩 시드 데이터 생성.

    face_embeddings.json (실제 영상에서 InsightFace ArcFace로 추출한 512차원 벡터)을
    읽어서 FaceIdentity + FaceExemplar를 Postgres pgvector에 저장.
    """
    json_path = os.path.join(os.path.dirname(__file__), "seed_data", "face_embeddings.json")
    with open(json_path) as f:
        data = json.load(f)

    identities_data = data["identities"] + data.get("merge_test_identities", [])
    identity_count = 0
    exemplar_count = 0

    for i, ident_data in enumerate(identities_data):
        video_id = face_video_ids[i % len(face_video_ids)]

        # exemplar 중 가장 높은 품질 점수
        best_quality = max(ex["quality"] for ex in ident_data["exemplars"])

        identity = FaceIdentity(
            org_id=org_id,
            cluster_id=ident_data["cluster_id"],
            centroid_embedding=ident_data["centroid_embedding"],
            exemplar_count=len(ident_data["exemplars"]),
            best_quality=best_quality,
            best_thumbnail_video_id=video_id,
        )
        session.add(identity)
        await session.flush()
        identity_count += 1

        for j, ex in enumerate(ident_data["exemplars"]):
            scene_id = f"{video_id}_scene_{j:03d}"
            exemplar = FaceExemplar(
                identity_id=identity.id,
                org_id=org_id,
                video_id=video_id,
                scene_id=scene_id,
                embedding=ex["embedding"],
                quality=ex["quality"],
                bbox_json=ex["bbox"],
            )
            session.add(exemplar)
            exemplar_count += 1

    await session.flush()
    logger.info("seeded_faces", identities=identity_count, exemplars=exemplar_count)


async def seed_opensearch(org, libraries, profiles, people_clusters, drive_entries):
    logger.info("seeding_opensearch")
    
    client = OpenSearchClient()
    
    try:
        await client.ensure_index_exists()
        
        documents = []
        cluster_ids = [p.person_cluster_id for p in people_clusters]
        drive_nicknames = {d.source_fingerprint_hash: d.nickname for d in drive_entries}
        
        for lib_idx, (library, profile) in enumerate(zip(libraries, profiles)):
            num_videos = random.randint(10, 20)
            
            for video_idx in range(num_videos):
                video_id = str(uuid4())
                is_korean_lib = lib_idx == 0
                
                source_type = random.choice(["gdrive", "removable_disk", "local"])
                required_drive = None
                if source_type == "removable_disk":
                    fingerprint = random.choice(list(drive_nicknames.keys()))
                    required_drive = drive_nicknames[fingerprint]
                
                num_segments = random.randint(5, 15)
                current_ms = 0
                
                for seg_idx in range(num_segments):
                    segment_id = f"{video_id}_seg_{seg_idx:03d}"
                    duration_ms = random.randint(2000, 60000)
                    start_ms = current_ms
                    end_ms = current_ms + duration_ms
                    current_ms = end_ms + 100
                    
                    if is_korean_lib or random.random() < 0.3:
                        transcript = random.choice(KOREAN_TRANSCRIPTS)
                    else:
                        transcript = random.choice(ENGLISH_TRANSCRIPTS)
                    
                    segment_people = random.sample(
                        cluster_ids, k=random.randint(0, min(3, len(cluster_ids)))
                    )
                    
                    capture_time = datetime.now(timezone.utc) - timedelta(
                        days=random.randint(1, 365),
                        hours=random.randint(0, 23),
                    )
                    
                    embedding = generate_mock_embedding(transcript)
                    
                    doc = {
                        "org_id": str(org.id),
                        "library_id": str(library.id),
                        "library_profile_id": str(profile.id),
                        "library_name": library.name,
                        "video_id": video_id,
                        "segment_id": segment_id,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "transcript_raw": transcript,
                        "transcript_norm": transcript.lower(),
                        "source_type": source_type,
                        "required_drive_nickname": required_drive,
                        "people_cluster_ids": segment_people,
                        "capture_time": capture_time.isoformat(),
                        "ingest_time": datetime.now(timezone.utc).isoformat(),
                        "thumbnail_url": f"https://placeholder.heimdex.local/thumb/{segment_id}.jpg",
                        "sprite_url": f"https://placeholder.heimdex.local/sprite/{segment_id}.jpg",
                        "word_timing_uri": f"s3://heimdex-assets/{org.id}/timings/{segment_id}.json",
                        "embedding_vector": embedding,
                    }
                    
                    documents.append((segment_id, doc))
        
        batch_size = 100
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            await client.bulk_index(batch)
        
        logger.info("opensearch_seeding_complete", total_documents=len(documents))
        
    finally:
        await client.close()


async def seed_scenes(org, libraries, profiles, people_clusters, drive_entries, face_video_ids=None):
    """OpenSearch 장면(scenes) 인덱스 시드 데이터 생성.

    영상당 3~5개 장면 생성. 장면 transcript는 랜덤 샘플을 합쳐서 만듦.

    face_video_ids: seed_faces()와 공유하는 video UUID 목록.
    이 ID로 장면을 만들어야 FaceExemplar.video_id와 OpenSearch 장면이 조인됨.
    """
    logger.info("seeding_scenes")

    client = SceneSearchClient()

    # visual_embeddings.json에서 SigLIP2 768dim 벡터 풀 로드
    visual_path = os.path.join(os.path.dirname(__file__), "seed_data", "visual_embeddings.json")
    try:
        with open(visual_path) as f:
            visual_data = json.load(f)
        # 영상별 임베딩을 전부 합쳐서 하나의 풀로 만듦
        visual_embedding_pool = [
            emb["embedding"]
            for video_embs in visual_data.get("videos", {}).values()
            for emb in video_embs
        ]
        logger.info("loaded_visual_embeddings", count=len(visual_embedding_pool))
    except FileNotFoundError:
        visual_embedding_pool = []
        logger.warning("visual_embeddings_not_found", path=visual_path)

    try:
        await client.ensure_index_exists()

        documents: list[tuple[str, dict]] = []
        cluster_ids = [p.person_cluster_id for p in people_clusters]
        drive_nicknames = {d.source_fingerprint_hash: d.nickname for d in drive_entries}

        for lib_idx, (library, profile) in enumerate(zip(libraries, profiles)):
            num_videos = random.randint(5, 10)
            is_korean_lib = lib_idx == 0

            if lib_idx == 0:
                title_pool = KOREAN_VIDEO_TITLES
            elif lib_idx == 2:
                title_pool = TRAINING_VIDEO_TITLES
            else:
                title_pool = ENGLISH_VIDEO_TITLES

            # 첫 번째 라이브러리에 face_video_ids 포함 → FaceExemplar와 조인 가능
            if lib_idx == 0 and face_video_ids:
                preset_video_ids = list(face_video_ids)
                num_videos = max(num_videos, len(preset_video_ids))
            else:
                preset_video_ids = []

            for video_idx in range(num_videos):
                if preset_video_ids:
                    video_id = preset_video_ids.pop(0)
                else:
                    video_id = str(uuid4())
                video_title = title_pool[video_idx % len(title_pool)]

                source_type = random.choice(["gdrive", "removable_disk", "local"])
                required_drive = None
                if source_type == "removable_disk":
                    fingerprint = random.choice(list(drive_nicknames.keys()))
                    required_drive = drive_nicknames[fingerprint]

                capture_time = datetime.now(timezone.utc) - timedelta(
                    days=random.randint(1, 365),
                    hours=random.randint(0, 23),
                )

                num_scenes = random.randint(3, 5)
                current_ms = 0

                for scene_idx in range(num_scenes):
                    scene_id = f"{video_id}_scene_{scene_idx:03d}"

                    duration_ms = random.randint(10000, 90000)
                    start_ms = current_ms
                    end_ms = current_ms + duration_ms
                    current_ms = end_ms

                    num_speech_segments = random.randint(2, 4)
                    transcript_pool = KOREAN_TRANSCRIPTS if (is_korean_lib or random.random() < 0.3) else ENGLISH_TRANSCRIPTS
                    transcript_parts = [
                        random.choice(transcript_pool)
                        for _ in range(num_speech_segments)
                    ]
                    transcript_raw = " ".join(transcript_parts)

                    scene_people = random.sample(
                        cluster_ids, k=random.randint(0, min(3, len(cluster_ids)))
                    )

                    embedding = generate_mock_embedding(transcript_raw)

                    doc = {
                        "org_id": str(org.id),
                        "library_id": str(library.id),
                        "video_id": video_id,
                        "video_title": video_title,
                        "scene_id": scene_id,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "transcript_raw": transcript_raw,
                        "transcript_norm": transcript_raw.lower(),
                        "transcript_char_count": len(transcript_raw),
                        "speech_segment_count": num_speech_segments,
                        "source_type": source_type,
                        "required_drive_nickname": required_drive,
                        "people_cluster_ids": scene_people,
                        "keyword_tags": random.sample(KEYWORD_TAGS_POOL, k=random.randint(0, 3)),
                        "product_tags": random.sample(PRODUCT_TAGS_POOL, k=random.randint(0, 2)),
                        "product_entities": random.sample(PRODUCT_ENTITIES_POOL, k=random.randint(0, 2)),
                        "ai_tags": random.sample(AI_TAGS_POOL, k=random.randint(0, 2)),
                        "capture_time": capture_time.isoformat(),
                        "ingest_time": datetime.now(timezone.utc).isoformat(),
                        "thumbnail_url": f"https://placeholder.heimdex.local/thumb/{scene_id}.jpg",
                        "keyframe_timestamp_ms": (start_ms + end_ms) // 2,
                        "embedding_vector": embedding,
                    }

                    # visual_embedding (SigLIP2 768dim) — 풀에서 랜덤 할당
                    if visual_embedding_pool:
                        doc["visual_embedding"] = random.choice(visual_embedding_pool)

                    documents.append((scene_id, doc))

        batch_size = 100
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            await client.bulk_index_scenes(batch)

        logger.info("scene_seeding_complete", total_documents=len(documents))

    finally:
        await client.close()


async def main():
    try:
        await seed_database()
        logger.info("seeding_complete")
    except Exception as e:
        logger.exception("seeding_failed", error=str(e))
        raise


if __name__ == "__main__":
    asyncio.run(main())
