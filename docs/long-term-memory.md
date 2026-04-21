# Phân tích cơ chế long-term memory trong hệ thống

## Bối cảnh bài toán

Với chatbot y tế, nhiều thông tin người dùng có tính **bền vững theo thời gian** (dị ứng, bệnh nền, thói quen, preference giao tiếp), nhưng không nên nhét toàn bộ vào short-term context mỗi lượt.

Long-term memory được thiết kế để giải mâu thuẫn:

- vừa lưu được dữ kiện có giá trị xuyên phiên chat,
- vừa giữ prompt hiện tại gọn và ổn định.

Nếu không có tầng này, hệ thống sẽ rơi vào một trong hai trạng thái xấu:

1. quên ngữ cảnh cá nhân sau mỗi phiên,
2. hoặc mang quá nhiều lịch sử vào prompt gây nhiễu và tốn token.

---

## Luận điểm kiến trúc: cấu trúc lai Postgres + Vector DB

Hệ thống chọn mô hình lai:

- **Postgres (`user_health_facts`)**: nguồn dữ liệu chuẩn, có ràng buộc identity, cập nhật và audit timestamp.
- **Qdrant**: lớp truy vấn ngữ nghĩa theo embedding để lấy memory phù hợp với query hiện tại.

Ý nghĩa của thiết kế này:

- Postgres giải quyết tính nhất quán dữ liệu fact.
- Qdrant giải quyết khả năng truy hồi theo ngữ nghĩa (semantic recall).

Nói ngắn gọn: Postgres là "source of truth", Qdrant là "retrieval accelerator".

---

## Luồng runtime thực tế

Trong `services/chat/orchestrator.py`, long-term memory đi theo hai pha độc lập.

### Pha 1: Retrieve trước khi tạo câu trả lời

- Từ `normalized_user_message`, hệ thống gọi `LongTermMemoryService.retrieve()`.
- Nếu vector search thành công: lấy `vector_ids` từ Qdrant -> đọc bản ghi từ Postgres theo thứ tự hit.
- Nếu vector search lỗi hoặc rỗng: fallback sang `list_recent_by_user(limit=fallback_limit)`.

Kết quả retrieval được đưa vào `AgentContext.long_term_memories` để LLM có thêm thông tin cá nhân liên quan.

### Pha 2: Remember sau khi đã có assistant reply (background)

- Background task gọi `remember_interaction()`.
- Extractor trích fact ứng viên từ cặp user/assistant message.
- Chuẩn hóa + lọc confidence + giới hạn số lượng write.
- Upsert vào Postgres và upsert vector vào Qdrant.

Tách ghi nhớ ra background là quyết định đúng cho latency: response không phải chờ pipeline ghi nhớ hoàn tất.

---

## Phân tích logic lưu trữ và đồng bộ

### 1) Identity và upsert

`repositories/long_term_memories.py` dùng khóa duy nhất:

- `(user_id, entity_type, entity_key, attribute_key, canonical_value)`

Điều này buộc hệ thống suy nghĩ theo “fact identity” thay vì “mỗi message một bản ghi”. Đây là điểm quan trọng để tránh phình dữ liệu và trùng fact.

### 2) Canonical hóa cho mutable facts

Extractor chuẩn hóa canonical cho các chỉ số biến thiên (BP, glucose, BMI, cân nặng,...) về `__latest__`.

Tác động:

- đảm bảo fact mới thay thế fact cũ theo cùng identity,
- giảm trùng lặp bản chất "đo lại cùng một loại chỉ số".

### 3) Cơ chế overwrite có kiểm soát

`LongTermMemoryService` có danh sách `_MUTABLE_FACT_ATTRIBUTE_KEYS` và `_SINGLETON_ATTRIBUTE_KEYS`.

Khi ghi fact thuộc nhóm này, hệ thống chủ động:

- deactivate các bản ghi active cũ cùng attribute,
- giữ bản ghi mới là active.

Đây là cơ chế bảo toàn "single source of current truth" cho các thuộc tính chỉ nên có một giá trị hiện hành.

---

## Phân tích retrieval quality

### 1) Ưu điểm

- Có filter `user_id` + `is_active` ngay trong Qdrant query, hạn chế nhiễu chéo user.
- Có fallback recent list khi semantic retrieval không trả kết quả.
- Có `touch()` cập nhật `last_accessed_at`, giúp fallback theo recency phản ánh usage thực.

### 2) Điểm cần lưu ý

- Fallback recent-by-user không dựa ngữ nghĩa; nếu `fallback_limit` lớn quá sẽ kéo nhiều fact ít liên quan.
- Chất lượng retrieval phụ thuộc mạnh vào chất lượng `content` dùng để embed (extractor tạo câu summary fact).

---

## Các tham số cấu hình và ý nghĩa vận hành

Nguồn config: `memory.long_term` trong `configs/ai_config.yaml`, nạp vào `configs/config.py`.

Các tham số chính:

- `top_k` (`LONG_TERM_MEMORY_TOP_K`): số memory lấy theo semantic search.
- `fallback_limit` (`LONG_TERM_MEMORY_FALLBACK_LIMIT`): số memory lấy theo recency khi fallback.
- `max_write_items` (`LONG_TERM_MEMORY_MAX_WRITE_ITEMS`): giới hạn số candidate được ghi mỗi lượt.
- `min_confidence` (`LONG_TERM_MEMORY_MIN_CONFIDENCE`): ngưỡng lọc fact trước khi ghi.
- `max_content_chars` (`LONG_TERM_MEMORY_MAX_CONTENT_CHARS`): giới hạn độ dài content fact trước embedding.

Giá trị hiện tại trong project:

- `top_k: 5`
- `fallback_limit: 5`
- `max_write_items: 3`
- `min_confidence: 0.8`
- `max_content_chars: 200`

Diễn giải: cấu hình đang nghiêng về **precision** (lọc khá chặt) hơn **recall** (ghi rộng).

---

## Rủi ro kỹ thuật cần theo dõi

1. **Schema drift giữa Postgres và payload vector**  
   Nếu payload ở Qdrant không cập nhật theo thay đổi field logic, retrieval có thể trả kết quả thiếu đồng nhất.

2. **Extraction drift do prompt/model thay đổi**  
   LLM extractor thay đổi hành vi có thể làm canonical/value_json không ổn định.

3. **Over-deactivation**  
   Nếu attribute bị phân loại nhầm vào nhóm mutable/singleton, hệ thống có thể deactivate fact hợp lệ quá mức.

4. **Silent failures ở background**  
   Ghi nhớ chạy nền; lỗi ingestion vector có thể không làm request fail nhưng chất lượng memory giảm dần nếu không theo dõi log/trace.

---

## Khuyến nghị vận hành (góc nhìn quyết định)

### Khi muốn tăng độ “nhớ đúng”

- tăng nhẹ `top_k` (ví dụ 5 -> 6),
- giữ `min_confidence` cao,
- tối ưu prompt extraction để output ổn định hơn thay vì chỉ nới ngưỡng.

### Khi muốn tăng recall ban đầu (giai đoạn khám phá)

- tăng `max_write_items`,
- hạ nhẹ `min_confidence`,
- nhưng cần dashboard/đánh giá để tránh memory rác tích tụ.

### Khi gặp nhiễu memory trong câu trả lời

- giảm `fallback_limit`,
- siết `max_content_chars` để nội dung fact cô đọng,
- rà lại canonicalization cho attribute thường nhiễu.

---

## Kết luận

Long-term memory hiện tại có nền tảng thiết kế tốt: tách rõ retrieve/remember, dùng identity-based upsert, và có cơ chế overwrite cho mutable facts.

Điểm then chốt để giữ chất lượng lâu dài không nằm ở việc "ghi nhiều hơn", mà ở việc **duy trì ổn định extraction + canonicalization + ngưỡng confidence**.  
Trong bối cảnh y tế, đây là bài toán ưu tiên precision có kiểm soát hơn là recall thuần túy.
