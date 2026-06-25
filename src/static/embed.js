/**
 * LeadCapture AI — Chatbot Embed Widget
 * Businesses paste this single <script> tag into their website.
 * Communicates with the backend via Server-Sent Events for real-time chat.
 */

(function () {
    'use strict';

    // Get business ID from script src
    var scripts = document.getElementsByTagName('script');
    var currentScript = scripts[scripts.length - 1];
    var src = currentScript.src || '';
    var params = new URLSearchParams(src.split('?')[1] || '');
    var BUSINESS_ID = params.get('business_id') || '0';
    var API_BASE = params.get('api_url') || window.location.origin;

    // Don't initialize if already loaded
    if (window.__LCAI_LOADED) return;
    window.__LCAI_LOADED = true;

    // ---- Styles ----
    var styles = document.createElement('style');
    styles.textContent = `
        #lcai-chatbot-widget {
            all: initial;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 999999;
            direction: ltr;
        }
        #lcai-chatbot-widget * {
            box-sizing: border-box;
        }
        #lcai-chatbot-toggle {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: #2563eb;
            color: white;
            border: none;
            cursor: pointer;
            font-size: 28px;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-left: auto;
        }
        #lcai-chatbot-toggle:hover {
            transform: scale(1.05);
            box-shadow: 0 6px 20px rgba(37, 99, 235, 0.5);
        }
        #lcai-chatbot-container {
            display: none;
            width: 380px;
            max-width: calc(100vw - 40px);
            height: 600px;
            max-height: calc(100vh - 100px);
            background: white;
            border-radius: 16px;
            box-shadow: 0 8px 40px rgba(0, 0, 0, 0.15);
            overflow: hidden;
            flex-direction: column;
            margin-bottom: 10px;
            animation: lcai-slideUp 0.3s ease;
        }
        #lcai-chatbot-container.open {
            display: flex;
        }
        @keyframes lcai-slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        #lcai-chatbot-header {
            background: #2563eb;
            color: white;
            padding: 16px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        #lcai-chatbot-header h3 {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
        }
        #lcai-chatbot-close {
            background: none;
            border: none;
            color: white;
            font-size: 20px;
            cursor: pointer;
            padding: 0;
            opacity: 0.8;
            transition: opacity 0.2s;
        }
        #lcai-chatbot-close:hover {
            opacity: 1;
        }
        #lcai-chatbot-messages {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            background: #f8fafc;
        }
        .lcai-message {
            margin-bottom: 12px;
            display: flex;
            flex-direction: column;
        }
        .lcai-message.bot {
            align-items: flex-start;
        }
        .lcai-message.user {
            align-items: flex-end;
        }
        .lcai-message .bubble {
            max-width: 85%;
            padding: 10px 14px;
            border-radius: 14px;
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
        }
        .lcai-message.bot .bubble {
            background: white;
            color: #1e293b;
            border-bottom-left-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .lcai-message.user .bubble {
            background: #2563eb;
            color: white;
            border-bottom-right-radius: 4px;
        }
        .lcai-message.bot .bubble.typing {
            background: #e2e8f0;
            display: flex;
            gap: 4px;
            padding: 14px 18px;
        }
        .lcai-message.bot .bubble.typing span {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #94a3b8;
            animation: lcai-bounce 1.4s infinite ease-in-out;
        }
        .lcai-message.bot .bubble.typing span:nth-child(1) { animation-delay: 0s; }
        .lcai-message.bot .bubble.typing span:nth-child(2) { animation-delay: 0.2s; }
        .lcai-message.bot .bubble.typing span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes lcai-bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }
        #lcai-chatbot-input-area {
            display: flex;
            padding: 12px;
            border-top: 1px solid #e2e8f0;
            background: white;
        }
        #lcai-chatbot-input {
            flex: 1;
            border: 1px solid #e2e8f0;
            border-radius: 24px;
            padding: 10px 16px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        #lcai-chatbot-input:focus {
            border-color: #2563eb;
        }
        #lcai-chatbot-send {
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            margin-left: 8px;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
        }
        #lcai-chatbot-send:hover {
            background: #1d4ed8;
        }
        #lcai-chatbot-send:disabled {
            background: #94a3b8;
            cursor: not-allowed;
        }
        .lcai-error {
            color: #dc2626;
            font-size: 13px;
            text-align: center;
            padding: 8px;
            background: #fef2f2;
            border-radius: 8px;
            margin: 8px 0;
        }
    `;
    document.head.appendChild(styles);

    // ---- Widget HTML ----
    var widget = document.createElement('div');
    widget.id = 'lcai-chatbot-widget';
    widget.innerHTML = `
        <div id="lcai-chatbot-container">
            <div id="lcai-chatbot-header">
                <h3>💬 Chat with us</h3>
                <button id="lcai-chatbot-close">&times;</button>
            </div>
            <div id="lcai-chatbot-messages">
                <div class="lcai-message bot">
                    <div class="bubble">Hi! 👋 How can we help you today? Feel free to ask about our services, book an appointment, or get a quote!</div>
                </div>
            </div>
            <div id="lcai-chatbot-input-area">
                <input type="text" id="lcai-chatbot-input" placeholder="Type your message..." autocomplete="off">
                <button id="lcai-chatbot-send">➤</button>
            </div>
        </div>
        <button id="lcai-chatbot-toggle">💬</button>
    `;
    document.body.appendChild(widget);

    // ---- State ----
    var container = document.getElementById('lcai-chatbot-container');
    var toggleBtn = document.getElementById('lcai-chatbot-toggle');
    var closeBtn = document.getElementById('lcai-chatbot-close');
    var messagesEl = document.getElementById('lcai-chatbot-messages');
    var inputEl = document.getElementById('lcai-chatbot-input');
    var sendBtn = document.getElementById('lcai-chatbot-send');

    var conversationId = null;
    var isWaiting = false;

    // ---- Functions ----
    function toggleWidget() {
        var isOpen = container.classList.contains('open');
        if (isOpen) {
            container.classList.remove('open');
            toggleBtn.style.display = 'flex';
        } else {
            container.classList.add('open');
            toggleBtn.style.display = 'none';
            inputEl.focus();
            if (!conversationId) {
                createConversation();
            }
        }
    }

    function addMessage(text, role) {
        var div = document.createElement('div');
        div.className = 'lcai-message ' + role;
        div.innerHTML = '<div class="bubble">' + escapeHtml(text) + '</div>';
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function showTyping() {
        var div = document.createElement('div');
        div.className = 'lcai-message bot';
        div.id = 'lcai-typing-indicator';
        div.innerHTML = '<div class="bubble typing"><span></span><span></span><span></span></div>';
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function hideTyping() {
        var typing = document.getElementById('lcai-typing-indicator');
        if (typing) typing.remove();
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function setWaiting(waiting) {
        isWaiting = waiting;
        sendBtn.disabled = waiting;
        inputEl.disabled = waiting;
        if (!waiting) inputEl.focus();
    }

    async function createConversation() {
        try {
            var resp = await fetch(API_BASE + '/api/chat/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ business_id: parseInt(BUSINESS_ID) })
            });
            var data = await resp.json();
            conversationId = data.conversation_id;
        } catch (e) {
            console.error('LeadCapture AI: Failed to start conversation', e);
        }
    }

    async function sendMessage() {
        var text = inputEl.value.trim();
        if (!text || isWaiting || !conversationId) return;

        inputEl.value = '';
        addMessage(text, 'user');
        setWaiting(true);
        showTyping();

        try {
            var eventSource = new EventSource(
                API_BASE + '/api/chat/stream?conversation_id=' + conversationId +
                '&business_id=' + BUSINESS_ID + '&message=' + encodeURIComponent(text)
            );

            var botResponse = '';
            var hasContent = false;

            eventSource.onmessage = function (e) {
                if (e.data === '[DONE]') {
                    eventSource.close();
                    hideTyping();
                    setWaiting(false);
                    if (!hasContent) {
                        addMessage('Sorry, I encountered an error. Please try again.', 'bot');
                    }
                    return;
                }

                try {
                    var parsed = JSON.parse(e.data);
                    if (parsed.content) {
                        if (!hasContent) {
                            hideTyping();
                            hasContent = true;
                        }
                        botResponse += parsed.content;
                        // Update or create bot message
                        var msgs = messagesEl.querySelectorAll('.lcai-message.bot:not(#lcai-typing-indicator)');
                        var lastBot = msgs[msgs.length - 1];
                        if (lastBot && lastBot.dataset.streaming) {
                            lastBot.querySelector('.bubble').textContent = botResponse;
                        } else {
                            var div = document.createElement('div');
                            div.className = 'lcai-message bot';
                            div.dataset.streaming = 'true';
                            div.innerHTML = '<div class="bubble">' + escapeHtml(botResponse) + '</div>';
                            messagesEl.appendChild(div);
                        }
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                    } else if (parsed.error) {
                        hideTyping();
                        addMessage(parsed.error, 'bot');
                        setWaiting(false);
                    }
                } catch (err) {
                    // ignore
                }
            };

            eventSource.onerror = function () {
                eventSource.close();
                hideTyping();
                if (!hasContent) {
                    addMessage('Sorry, I encountered an error. Please try again.', 'bot');
                }
                setWaiting(false);
            };

        } catch (e) {
            hideTyping();
            addMessage('Sorry, we could not connect. Please try again.', 'bot');
            setWaiting(false);
        }
    }

    // ---- Event listeners ----
    toggleBtn.addEventListener('click', toggleWidget);
    closeBtn.addEventListener('click', toggleWidget);
    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') sendMessage();
    });
})();
