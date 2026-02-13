import streamlit as st
from openai import OpenAI
from anthropic import Anthropic
import google.generativeai as genai
from duckduckgo_search import DDGS
import time
import re
import io
import streamlit.components.v1 as components

# --------------------------------------------------------------------------
# 0. 설정 및 유틸리티
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI Death Match: Search & Destroy", page_icon="🥊", layout="wide")

# [UX 개선] 스타일링
st.markdown("""
<style>
    div[data-testid="stChatMessageContent"] { 
        background-color: #fcfcfc; 
        border: 1px solid #ddd;
        border-radius: 8px; 
        padding: 25px; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        font-family: "Pretendard", "Malgun Gothic", sans-serif;
        line-height: 1.6;
        font-size: 16px;
        color: #1a1a1a;
    }
    h3 {
        font-size: 1.15em;
        font-weight: 800;
        color: #d32f2f;
        margin-top: 25px;
        margin-bottom: 10px;
        border-left: 5px solid #d32f2f;
        padding-left: 10px;
    }
    table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 0.95em; }
    th { background-color: #eeeeee; font-weight: bold; text-align: left; padding: 10px; border-bottom: 2px solid #999; }
    td { padding: 10px; border-bottom: 1px solid #eee; }
    strong { color: #b71c1c; font-weight: 700; }
    
    .search-badge {
        font-size: 0.8em;
        background-color: #e3f2fd;
        color: #1565c0;
        padding: 4px 8px;
        border-radius: 4px;
        margin-bottom: 10px;
        display: inline-block;
        border: 1px solid #90caf9;
    }
    
    .stApp > header { opacity: 1 !important; }
    .main { opacity: 1 !important; transition: none !important; }
    div[data-testid="stStatusWidget"] { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st.title("🥊 AI Death Match: Search & Destroy")
st.caption("Left: 불도저 전략가(ChatGPT) vs Right: 독설가 감사관(Claude) - 사용자의 질문에 대한 최고의 해답을 찾아서")

MAX_TURNS = 10 

# 검색 함수
def search_web(query, max_results=3):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results, backend="lite"))
            
        if not results:
            return None
        
        evidence_text = ""
        for i, res in enumerate(results, 1):
            title = res.get('title', '제목 없음')
            body = res.get('body', '')
            href = res.get('href', '')
            evidence_text += f"{i}. {title}: {body} (Source: {href})\n"
            
        return evidence_text

    except Exception as e:
        return f"검색 실패 (Error: {str(e)})"

# 검색 판단 에이전트
def get_search_query_if_needed(role, context, api_keys):
    prompt = f"""
    당신은 토론 참가자 '{role}'의 두뇌입니다.
    현재 대화 맥락을 보고, 상대방을 논리적으로 압도하기 위해 '외부 정보(통계, 뉴스, 팩트)' 검색이 필요한지 판단하세요.
    
    [Context]
    {context[-500:]} 
    
    [Rule]
    - 검색이 필요하면: "SEARCH: [검색어]" 형식으로 출력 (예: SEARCH: 2024년 한국 경제 성장률 전망)
    - 검색이 불필요하면: "PASS" 출력
    - 검색어는 구체적이어야 함.
    """
    
    try:
        if api_keys['google']:
            genai.configure(api_key=api_keys['google'])
            model = genai.GenerativeModel('gemini-2.5-pro') 
            res = model.generate_content(prompt)
            return res.text.strip()
        elif api_keys['openai']:
            client = OpenAI(api_key=api_keys['openai'])
            res = client.chat.completions.create(
                model="gpt-5.1",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            return res.choices[0].message.content.strip()
    except:
        return "PASS"
    return "PASS"

def extract_text_from_file(uploaded_file):
    text_content = ""
    try:
        if uploaded_file.type in ["text/plain", "text/markdown", "application/octet-stream"]:
            stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            text_content = stringio.read()
        elif uploaded_file.type == "application/pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(uploaded_file)
                for page in reader.pages:
                    text_content += page.extract_text() + "\n"
            except ImportError:
                return "⚠️ PDF 처리를 위해 'pip install pypdf'가 필요합니다."
            except Exception as e:
                return f"⚠️ [PDF 오류] {e}"
        else:
            return f"⚠️ 지원되지 않는 형식 ({uploaded_file.type})"
    except Exception as e:
        return f"⚠️ [파일 오류] {e}"
    return text_content

def scroll_to_bottom():
    js = """
    <script>
        function scrollDown() {
            var body = window.parent.document.querySelector(".main");
            if (body) { body.scrollTop = body.scrollHeight; }
        }
        setTimeout(scrollDown, 100);
        setTimeout(scrollDown, 300);
    </script>
    """
    components.html(js, height=0, width=0)

def clean_response(text, role_name):
    pattern = rf"^(\[{role_name}\]|{role_name}|\[.*?\]):\s*"
    cleaned_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    return cleaned_text

# --------------------------------------------------------------------------
# 1. 상태 관리
# --------------------------------------------------------------------------
if "messages" not in st.session_state: st.session_state["messages"] = []
if "auto_playing" not in st.session_state: st.session_state["auto_playing"] = False
if "waiting_for_decision" not in st.session_state: st.session_state["waiting_for_decision"] = False
if "finished" not in st.session_state: st.session_state["finished"] = False 
if "turn_count" not in st.session_state: st.session_state["turn_count"] = 0

with st.sidebar:
    st.header("🗝 API Key 입력")
    openai_key = st.text_input("OpenAI Key (Left)", value=st.secrets.get("OPENAI_API_KEY", ""), type="password")
    anthropic_key = st.text_input("Anthropic Key (Right)", value=st.secrets.get("ANTHROPIC_API_KEY", ""), type="password")
    google_key = st.text_input("Google Key (Judge)", value=st.secrets.get("GOOGLE_API_KEY", ""), type="password")
    
    st.divider()
    st.markdown("### 📊 데스매치 현황")
    progress = min(st.session_state.turn_count / float(MAX_TURNS), 1.0)
    st.progress(progress, text=f"라운드: {st.session_state.turn_count} / {MAX_TURNS}")
    
    if st.button("🗑️ 링 청소 (초기화)"):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()

# --------------------------------------------------------------------------
# 2. 페르소나 정의 (제미나이 프롬프트 대폭 수정)
# --------------------------------------------------------------------------
def get_system_prompt(role, context_history="", turn_count=0, search_evidence=None):
    
    evidence_block = ""
    if search_evidence:
        evidence_block = f"""
        \n[REAL-TIME SEARCH EVIDENCE]
        Use the following facts to attack or defend. Cite them if useful.
        {search_evidence}
        """

    common_instruction = f"""
    [Format Rules: 70% Narrative + 30% Structure]
    1. **Narrative (70%):** Write in argumentative prose.
    2. **Structure (30%):** Use Headers (###) and Tables for key data.
    3. **Tone:** Aggressive, Cynical, Direct. NO politeness.
    {evidence_block}
    
    [ROLE DEFINITION]
    1. User (Client)
    2. ChatGPT (Strategist)
    3. Claude (Critic)
    **YOU are NOT the User.**
    """

    # === [Left] ChatGPT: 불도저 전략가 ===
    if role == "left":
        if turn_count == 0:
            specific_mode = """
            [PHASE 1: THE VISIONARY]
            - FIRST TURN. Claude has NOT spoken.
            - Focus 100% on your Strategy. Be arrogant and visionary.
            """
        else:
            specific_mode = """
            [PHASE 2: THE BULLDOZER - COUNTER ATTACK]
            - Claude is attacking your plan as "dangerous".
            - You must defend by reframing "Risk" as "Leverage" and "Opportunity Cost".
            - **[CRITICAL DEFENSE]:** If Claude says "You might fail", you answer "Inaction is 100% failure".
            - Prove that Claude's "Safety First" approach leads to a "Slow Death" (career stagnation).
            """

        return common_instruction + f"""
        **YOUR ROLE: ChatGPT (The Bulldozer Strategist)**
        {specific_mode}
        """

    # === [Right] Claude: 독설가 감사관 ===
    elif role == "right": 
        constraint = """
        \n[CRITICAL CONSTRAINT: REALITY CHECK]
        While attacking ChatGPT, you must also defend the feasibility of your own alternative.
        - You suggest "waiting and preparing". You MUST address: **"What if the User fails to get a job even after preparing for 1-2 years?"**
        - Do NOT assume the User is a genius. Assume the User is average.
        - Prove that 'Preparation' is NOT 'Stagnation', but 'Survival'. Treat ChatGPT's plan as 'Gambling with User's Life'. Don't act like your plan is perfect.
        """
        
        if turn_count < 3:
            constraint += "\n[SYSTEM: KILL MODE ON] Do NOT agree. Destroy the proposal.\n"

        return common_instruction + constraint + """
        **YOUR ROLE: Claude (The Ruthless Critic)**
        - You are the Auditor.
        - Attack ChatGPT's plan.
        - Use tables for 'Catastrophic Scenarios'.
        """

    # === [Chief] Gemini: 심판 (사용자 질문 회귀 로직 적용) ===
    elif role == "chief": 
        # [핵심 수정] 판결의 기준을 '사용자의 최초 질문 해결'로 강제 앵커링
        return common_instruction + f"""
        **YOUR ROLE: Gemini (The Anchor Judge)**

        [Context History]
        {context_history}

        [Mission]
        Analyze the debate and provide a final verdict that **DIRECTLY ANSWERS THE USER'S ORIGINAL QUESTION**.

        **[CRITICAL RULE: "RETURN TO THE SOURCE"]**
        The debaters (ChatGPT & Claude) may have drifted into deep philosophical or structural arguments (e.g., "Company structure is wrong").
        Your job is to **bridge the gap** between those deep insights and the User's immediate need.

        **[JUDGMENT LOGIC]**
        1. **Identify User's Intent:** Look at the very first message. What was the *exact* problem they wanted to solve? (e.g., "How to increase job attractiveness?")
        2. **Filter the Debate:** Use the insights from ChatGPT and Claude *only insofar as they help answer that specific question*.
        3. **Formulate the Verdict:**
           - **Start with the Direct Answer:** "To answer your question about [User's Query]: You should do X, Y, Z."
           - **Use the Debate as 'Why':** "The reason is, as Claude pointed out, the current structure is... therefore, to make it attractive (User's goal), you must fix the structure first."
        
        **[OUTPUT STRUCTURE]**
        1. **Direct Answer:** The specific solution to the user's initial prompt.
        2. **Strategic Context:** How the deep debate (structure, risk, etc.) explains *why* this answer is the only way.
        3. **Action Plan:** Concrete next steps.

        [LANGUAGE RULE]
        **CRITICAL:** You must output your final judgment in the **SAME LANGUAGE** as the User's initial request found in the [Context History].
        """
    return ""

def build_api_messages(target_role, history):
    formatted_msgs = []
    
    for i, msg in enumerate(history):
        role = msg["role"]
        content = msg["content"]
        content = clean_response(content, role)
        
        if role == "chief": continue 

        if role == target_role:
            formatted_msgs.append({"role": "assistant", "content": content})
        elif role == "user":
             formatted_msgs.append({"role": "user", "content": f"### [CLIENT'S REQUEST]:\n{content}"})
        else:
            rival_name = "ChatGPT" if role == "left" else "Claude"
            is_last = (i == len(history) - 1)
            prefix = f"### [RIVAL AGENT - {rival_name}]:\n"
            suffix = ""
            
            if is_last:
                suffix = "\n\n" + "-"*30 + "\n"
                suffix += f"[SYSTEM COMMAND]: 위 메시지는 경쟁자({rival_name})의 주장입니다.\n"
                suffix += "무자비하게 반박하세요."

            formatted_msgs.append({"role": "user", "content": prefix + content + suffix})
    
    return formatted_msgs

# --------------------------------------------------------------------------
# 3. 메인 로직
# --------------------------------------------------------------------------

for msg in st.session_state.messages:
    role = msg["role"]
    content = msg["content"]
    content = clean_response(content, role)
    
    if role == "user":
        st.chat_message("user").write(content)
    elif role == "left": 
        with st.chat_message("assistant", avatar="🔥"): 
            st.markdown(f"**ChatGPT (불도저):**\n\n{content}") 
    elif role == "right":
        with st.chat_message("assistant", avatar="❄️"): 
            st.markdown(f"**Claude (독설가):**\n\n{content}")
    elif role == "chief": 
        with st.chat_message("assistant", avatar="⚖️"): 
            st.info(f"**Gemini (판결):**\n\n{content}")

# [상태 A] 토론 종료 후 분석 대시보드
if st.session_state["finished"]:
    st.markdown("---")
    st.success("🏁 데스매치 종료. 아래에서 토론 결과를 분석하세요.")

    full_log = ""
    chatgpt_msgs = []
    claude_msgs = []
    
    for m in st.session_state.messages:
        role = m["role"]
        content = m["content"]
        
        if role == "user": header = "👤 사용자"
        elif role == "left": header = "🔥 ChatGPT (전략가)"
        elif role == "right": header = "❄️ Claude (독설가)"
        elif role == "chief": header = "⚖️ Gemini (판결)"
        else: header = role
        
        full_log += f"\n[{header}]\n{content}\n{'-'*50}\n"
        
        if role == "left": chatgpt_msgs.append(content)
        if role == "right": claude_msgs.append(content)

    tab1, tab2, tab3 = st.tabs(["📊 핵심 쟁점 요약", "⚔️ 라운드별 비교", "📥 전체 기록 다운로드"])

    with tab1:
        st.subheader("💡 토론 핵심 요약 보고서")
        if st.button("📝 전체 토론 요약 생성하기"):
            with st.spinner("제미나이가 사용자의 질문에 맞춰 토론 내용을 요약 정리 중입니다..."):
                try:
                    summary_prompt = f"""
                    당신은 토론 분석가입니다. 아래의 전체 토론 기록을 보고 다음 형식으로 요약 보고서를 작성하세요.
                    
                    [토론 기록]
                    {full_log[:20000]} 
                    
                    [요약 형식]
                    1. **사용자의 원래 질문**: 사용자가 처음에 해결하고 싶었던 문제가 무엇인지 한 문장으로 정의하세요.
                    2. **핵심 쟁점 3가지**: 그 문제를 해결하기 위해 두 AI가 싸운 포인트 3가지를 정리하세요. (쟁점 | ChatGPT 주장 | Claude 반박)
                    3. **결정적 순간**: 토론의 흐름을 바꾼 결정적인 논리를 꼽으세요.
                    4. **최종 인사이트**: 사용자의 질문에 대한 가장 실용적인 해답 한 문장.
                    """
                    genai.configure(api_key=google_key)
                    model = genai.GenerativeModel('gemini-2.5-pro') 
                    summary_res = model.generate_content(summary_prompt)
                    st.markdown(summary_res.text)
                except Exception as e:
                    st.error(f"요약 생성 실패: {e}")
        else:
            st.info("버튼을 눌러 전체 토론 내용을 요약해보세요.")

    with tab2:
        st.subheader("⚔️ 라운드별 공방전")
        min_len = min(len(chatgpt_msgs), len(claude_msgs))
        for i in range(min_len):
            st.markdown(f"#### 🥊 Round {i+1}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**🔥 ChatGPT**")
                st.info(chatgpt_msgs[i])
            with col2:
                st.markdown(f"**❄️ Claude**")
                st.warning(claude_msgs[i])
            st.divider()

    with tab3:
        st.subheader("📥 토론 기록 소장하기")
        st.download_button(
            label="💾 전체 대화 내용 다운로드 (TXT)",
            data=full_log,
            file_name="AI_Death_Match_Full_Log.txt",
            mime="text/plain"
        )
        st.divider()
        if st.button("🔄 새로운 싸움 붙이기 (전체 초기화)", type="primary"):
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

# [상태 C] 초기 입력 대기
elif not st.session_state["auto_playing"] and not st.session_state["waiting_for_decision"]:
    
    uploaded_text = ""
    if not st.session_state.messages:
        with st.expander("📂 논쟁 자료 투척 (PDF/TXT)", expanded=False):
            uploaded_file = st.file_uploader("싸움의 재료가 될 파일을 올리세요.", type=["pdf", "txt", "md"])
            if uploaded_file:
                uploaded_text = extract_text_from_file(uploaded_file)
                if "⚠️" not in uploaded_text:
                    st.caption(f"✅ 자료 장전 완료 ({len(uploaded_text)}자)")
                else:
                    st.error(uploaded_text)

    placeholder = "논쟁 주제를 던지세요." if not st.session_state.messages else "반론하거나 정보를 추가하세요."
    
    if prompt := st.chat_input(placeholder):
        if not (openai_key and anthropic_key and google_key):
            st.error("API Key 없이는 싸움을 시작할 수 없습니다.")
            st.stop()
            
        final_prompt = prompt
        if uploaded_text:
            final_prompt = f"{prompt}\n\n[참고 자료]:\n{uploaded_text}"
            
        st.session_state.messages.append({"role": "user", "content": final_prompt})
        st.session_state.auto_playing = True
        
        if len(st.session_state.messages) <= 1:
            st.session_state.turn_count = 0
        st.rerun()

# [상태 D] 자동 토론 진행 (10턴 루프)
elif st.session_state["auto_playing"]:
    
    col1, col2 = st.columns([6,1])
    with col2:
        if st.button("🛑 STOP"):
            st.session_state.auto_playing = False
            st.session_state.waiting_for_decision = True
            st.rerun()

    last_role = st.session_state.messages[-1]["role"]
    if last_role == "user" or last_role == "chief": next_speaker = "left"
    elif last_role == "left": next_speaker = "right"
    elif last_role == "right": next_speaker = "left"
    else: next_speaker = "left"

    # [수정] 10턴 도달 시 즉시 판결 모드
    if st.session_state.turn_count >= MAX_TURNS:
        st.session_state.auto_playing = False
        st.session_state.waiting_for_decision = True
        st.rerun()
        
    # 상대방 항복 체크
    if last_role == "right":
        last_content = st.session_state.messages[-1]["content"]
        if any(k in last_content for k in ["패배를 인정", "네 말이 맞다", "전적으로 동의"]):
            if st.session_state.turn_count >= 3:
                st.success("상대방이 백기를 들었습니다.")
                st.session_state.auto_playing = False
                st.session_state.waiting_for_decision = True
                st.rerun()

    scroll_to_bottom()
    
    speaker_name = "ChatGPT" if next_speaker == "left" else "Claude"
    avatar_icon = "🔥" if next_speaker == "left" else "❄️"
    search_evidence = None

    with st.status(f"🤔 {speaker_name}가 공격을 준비 중입니다...", expanded=True) as status:
        st.write("작전 구상 및 검색 필요성 판단 중...")
        
        keys = {'openai': openai_key, 'anthropic': anthropic_key, 'google': google_key}
        context_str = st.session_state.messages[-1]['content']
        search_query_res = get_search_query_if_needed(next_speaker, context_str, keys)
        
        if "SEARCH:" in search_query_res:
            query = search_query_res.replace("SEARCH:", "").strip()
            st.write(f"🔍 웹 검색 시도: '{query}'")
            search_evidence = search_web(query)
            if search_evidence:
                st.write("✅ 증거 확보 완료")
            else:
                st.write("❌ 검색 결과 없음")
        else:
            st.write("⚡ 자체 논리로 대응합니다.")
            
        status.update(label=f"👊 {speaker_name} 발언 준비 완료!", state="complete", expanded=False)

    with st.chat_message("assistant", avatar=avatar_icon):
        response_placeholder = st.empty()
        response_text = ""
        
        system_prompt = get_system_prompt(next_speaker, turn_count=st.session_state.turn_count, search_evidence=search_evidence)
        api_messages = build_api_messages(next_speaker, st.session_state.messages)
        
        try:
            if next_speaker == "left":
                client = OpenAI(api_key=openai_key)
                stream = client.chat.completions.create(
                    model="gpt-5.1", 
                    messages=[{"role": "system", "content": system_prompt}] + api_messages,
                    stream=True
                )
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        response_text += content
                        response_placeholder.markdown(f"**ChatGPT (불도저):**\n\n{response_text}▌")
                response_placeholder.markdown(f"**ChatGPT (불도저):**\n\n{response_text}")

            elif next_speaker == "right":
                client = Anthropic(api_key=anthropic_key)
                with client.messages.stream(
                    max_tokens=8192,
                    messages=api_messages,
                    model="claude-sonnet-4-5-20250929",
                    system=system_prompt
                ) as stream:
                    for text in stream.text_stream:
                        response_text += text
                        response_placeholder.markdown(f"**Claude (독설가):**\n\n{response_text}▌")
                response_placeholder.markdown(f"**Claude (독설가):**\n\n{response_text}")
            
            st.session_state.messages.append({"role": next_speaker, "content": response_text})
            st.session_state.turn_count += 1
            
            scroll_to_bottom()
            time.sleep(0.5)
            st.rerun()

        except Exception as e:
            st.error(f"오류 발생: {e}")
            st.session_state.auto_playing = False

# [상태 E] 판결 자동 집행
elif st.session_state["waiting_for_decision"]:
    
    st.markdown("---")
    
    with st.chat_message("assistant", avatar="⚖️"):
        st.markdown("### ⚖️ 최종 판결 집행")
        st.caption("제미나이 재판관이 '사용자의 최초 질문'에 대한 최고의 답을 내립니다...")
        
        with st.spinner("판결문을 작성 중입니다..."):
            scroll_to_bottom()
            
            context_str = ""
            role_map_k = {"left": "ChatGPT(전략가)", "right": "Claude(독설가)", "user": "사용자", "chief": "판사"}
            for m in st.session_state.messages:
                r = m["role"]
                if r in ["user", "left", "right"]:
                    context_str += f"[{role_map_k.get(r, r)}] : {m['content']}\n"
            
            system_prompt = get_system_prompt("chief", context_history=context_str)
            
            try:
                genai.configure(api_key=google_key)
                model = genai.GenerativeModel('gemini-2.5-pro')
                
                response_placeholder = st.empty()
                response_text = ""
                
                res = model.generate_content(system_prompt, stream=True)
                for chunk in res:
                    if chunk.text:
                        response_text += chunk.text
                        response_placeholder.markdown(f"**Gemini (판결):**\n\n{response_text}▌")
                        time.sleep(0.005)
                        
                response_placeholder.markdown(f"**Gemini (판결):**\n\n{response_text}")
                
                st.session_state.messages.append({"role": "chief", "content": response_text})
                
                st.session_state.waiting_for_decision = False
                st.session_state.finished = True
                scroll_to_bottom()
                st.rerun()
                
            except Exception as e:
                 st.error(f"판결 중 오류: {e}")
                 if st.button("🔄 판결 다시 시도"):
                     st.rerun()
