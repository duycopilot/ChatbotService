# Phân tích cơ chế token-aware LLM trong hệ thống

## Bối cảnh bài toán

Hệ thống đang giải một bài toán mâu thuẫn kinh điển của RAG chatbot y tế:

- Cần **nhiều ngữ cảnh** (history + tài liệu + memory) để trả lời đúng.
- Nhưng model chỉ có **context window hữu hạn**; vượt ngưỡng sẽ lỗi hoặc cắt ngữ cảnh không kiểm soát.

Vì vậy token-aware không phải là “tối ưu phụ”, mà là cơ chế kiểm soát rủi ro trung tâm để giữ 3 mục tiêu đồng thời:

1. tránh overflow context,
2. giữ thông tin lâm sàng quan trọng,
3. ổn định chất lượng/latency qua nhiều độ dài hội thoại.

---

## Luận điểm kiến trúc: hệ thống đang kiểm soát token ở hai tầng

### Tầng 1 — Short-term memory (trước khi vào generation)

`PostgresChatMemory` + `TokenAwareMemoryManager` xử lý lịch sử hội thoại theo hướng:

- đo token của toàn bộ recent turns,
- nếu vượt ngưỡng thì tóm tắt phần cũ,
- giữ nguyên một số turn mới nhất để bảo toàn tính liên tục đối thoại.

Tầng này giải quyết vấn đề “history phình to theo thời gian”.

### Tầng 2 — RAG generation budget (ngay trước khi gọi LLM)

`generate_answer()` thực hiện phân bổ ngân sách token giữa:

- document context,
- history messages,
- fixed overhead của prompt format.

Tầng này giải quyết vấn đề “prompt tại thời điểm gọi model có thể vẫn quá dài dù đã summarize”.

**Kết luận:** hai tầng bổ trợ nhau; bỏ một tầng thì tầng còn lại phải gánh quá tải và dễ fail ở tình huống biên.

---

## Phân tích cơ chế short-term token-aware

### 1) Token counting là nguồn sai số lớn nhất

Hệ thống hỗ trợ `auto/hf/tiktoken/simple` trong `create_token_counter()`.

Về bản chất:

- `hf` bám sát tokenizer model nhất (đổi lại phụ thuộc model artifacts),
- `tiktoken` ổn định nhưng có thể lệch với model non-OpenAI,
- `simple` nhanh nhưng chỉ là xấp xỉ ký tự.

Do đó, sự ổn định của budget phụ thuộc trực tiếp vào việc chọn đúng tokenizer strategy/model.

### 2) Ngưỡng summarize là cơ chế đổi “độ tươi” lấy “độ an toàn token”

`MEMORY_SUMMARIZATION_THRESHOLD_TOKENS` quyết định thời điểm nén history.

- Ngưỡng thấp: summarize sớm, an toàn overflow hơn nhưng tăng nguy cơ mất chi tiết.
- Ngưỡng cao: giữ chi tiết lâu hơn nhưng dễ dồn áp lực cho bước generation.

`MEMORY_SUMMARIZATION_KEEP_RECENT_TURNS` là van an toàn để tránh summarize “quá tay”.

### 3) Reserve tokens trong memory ảnh hưởng trực tiếp generation

`MEMORY_SUMMARIZATION_RESERVE_TOKENS` không chỉ phục vụ memory; nó đi thẳng vào công thức budget của generation.

Nói cách khác, đây là tham số “liên tầng”: chỉnh sai sẽ làm sai cân bằng toàn pipeline.

---

## Phân tích cơ chế budget trong RAG generation

Tại `services/chat/rag/query_pipeline/generation.py`, hệ thống dùng công thức:

$$
   ext{max\_input\_tokens}
= \text{LLM\_CONTEXT\_WINDOW}
- \text{LLM\_MAX\_TOKENS}
- \text{MEMORY\_SUMMARIZATION\_RESERVE\_TOKENS}
- \text{RAG\_GENERATION\_SAFETY\_MARGIN\_TOKENS}
$$

Sau đó trừ fixed overhead:

$$
   ext{fixed\_overhead}
= T(\text{SYSTEM\_PREFIX}) + T(\text{query}) + \text{RAG\_GENERATION\_TAG\_TOKENS}
$$

và chia biến số còn lại cho docs/history theo tỉ lệ:

$$
   ext{doc\_budget} = \lfloor \text{variable\_budget} \times \text{RAG\_GENERATION\_DOC\_BUDGET\_RATIO} \rfloor
$$

$$
   ext{history\_budget} = \text{variable\_budget} - \text{doc\_budget}
$$

Trong đó:

- `doc_prefix_tokens`, `role_format_overhead`, `tag_tokens` là các khoản “ma sát định dạng” (formatting friction).
- Nếu các khoản này thấp hơn thực tế, hệ thống sẽ lạc quan giả và overflow muộn.

---

## Ý nghĩa vận hành của 6 tham số generation mới

1. `safety_margin_tokens`  
   Biên an toàn cuối cùng trước context hard limit.

2. `doc_budget_ratio`  
   Cần xem như “đòn bẩy ưu tiên tri thức ngoài (docs) so với hội thoại trong (history)”.

3. `doc_prefix_tokens`  
   Khoản overhead cho mỗi tài liệu sau khi dựng prompt (đánh số `[N]`, tag, separator...).

4. `tag_tokens`  
   Overhead cố định do template/system scaffolding.

5. `role_format_overhead`  
   Overhead cho mỗi message history (role wrapper + format).

6. `max_history_turns`  
   Trần logic trước khi trim theo budget; đây là ràng buộc ngữ nghĩa, không chỉ ràng buộc token.

---

## Đánh đổi chính đang tồn tại trong cấu hình hiện tại

Theo config hiện tại:

- `max_history_turns = 2`
- `doc_budget_ratio = 0.60`
- `threshold_tokens = 1800`
- `reserve_tokens = 320`

Diễn giải:

- Hệ thống đang ưu tiên **độ an toàn context** hơn **độ sâu lịch sử hội thoại**.
- Điều này hợp lý với QA dựa tri thức tài liệu, nhưng có thể làm yếu khả năng theo dõi đối thoại nhiều lượt (multi-turn intent continuity).

Nói ngắn gọn: cấu hình hiện tại thiên về “retrieval-first” hơn “dialogue-first”.

---

## Rủi ro kỹ thuật cần theo dõi

1. **Sai lệch tokenizer giữa môi trường**  
   `auto` có thể chọn backend khác nhau giữa local/prod, dẫn đến drift token count.

2. **Overhead format bị underestimate**  
   Nếu prompt builder thay đổi nhưng `tag_tokens`/`role_format_overhead` không cập nhật, lỗi overflow sẽ xuất hiện “bất ngờ”.

3. **Summary drift**  
   Tóm tắt nhiều vòng có thể tích lũy mất mát thông tin y khoa quan trọng.

4. **Fallback quá mạnh**  
   Cơ chế bỏ history + giữ 1 doc giúp sống sót khi overflow, nhưng có thể làm giảm độ liên tục câu trả lời.

---

## Khuyến nghị vận hành (dạng phân tích quyết định)

### Khi mục tiêu là giảm lỗi context overflow

Ưu tiên tăng theo thứ tự:

1. `safety_margin_tokens`
2. `tag_tokens` / `role_format_overhead` (nếu prompt format dày)
3. giảm `doc_budget_ratio`
4. giảm `max_history_turns`

### Khi mục tiêu là tăng độ mạch hội thoại

- tăng `max_history_turns` (2 -> 3),
- giữ `doc_budget_ratio` vừa phải,
- cân nhắc giảm nhẹ `safety_margin_tokens` nếu hệ thống chưa gần trần context.

### Khi mục tiêu là tính nhất quán giữa local/staging/prod

- chuyển tokenizer sang `hf`,
- pin `tokenizer.model_name` trùng model serving,
- kiểm tra artifact tokenizer được đồng bộ giữa môi trường.

---

## Bản đồ tham số: config -> runtime

Nguồn: `configs/ai_config.yaml` -> nạp tại `configs/config.py` -> dùng trong runtime.

Các nhóm chính:

- Memory tokenizer/summarization:
  - `MEMORY_TOKENIZER_STRATEGY`
  - `MEMORY_TOKENIZER_MODEL_NAME`
  - `MEMORY_TOKENIZER_HF_LOCAL_FILES_ONLY`
  - `MEMORY_SUMMARIZATION_THRESHOLD_TOKENS`
  - `MEMORY_SUMMARIZATION_KEEP_RECENT_TURNS`
  - `MEMORY_SUMMARIZATION_RESERVE_TOKENS`

- Generation budget:
  - `RAG_GENERATION_MAX_HISTORY_TURNS`
  - `RAG_GENERATION_SAFETY_MARGIN_TOKENS`
  - `RAG_GENERATION_DOC_BUDGET_RATIO`
  - `RAG_GENERATION_DOC_PREFIX_TOKENS`
  - `RAG_GENERATION_TAG_TOKENS`
  - `RAG_GENERATION_ROLE_FORMAT_OVERHEAD`

---

## Kết luận

Thiết kế token-aware hiện tại là hợp lý và đã có đủ cơ chế phòng thủ nhiều lớp. Điểm cần quản trị tốt không nằm ở việc “có token-aware hay không”, mà nằm ở **hiệu chỉnh đúng 6 tham số generation và 3 tham số memory cốt lõi theo mục tiêu vận hành**.

Nếu cần một nguyên tắc ngắn gọn:  
**ưu tiên đo đúng token trước, rồi mới tối ưu tỉ lệ budget**. Sai số đo token luôn đắt hơn sai số tuning.
