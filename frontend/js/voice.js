// Web Speech API wrapper — voice input module

const Voice = (() => {
  const overlay      = document.getElementById('voiceOverlay');
  const statusEl     = document.getElementById('voiceStatus');
  const transcriptEl = document.getElementById('voiceTranscript');
  const resultEl     = document.getElementById('voiceResult');
  const cancelBtn    = document.getElementById('voiceCancelBtn');
  const doneBtn      = document.getElementById('voiceDoneBtn');
  const pulseEl      = document.querySelector('.voice-pulse');

  let recognition = null;
  let isListening = false;
  let finalText   = '';
  let cancelled   = false;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const supported = !!SpeechRecognition;

  function init() {
    if (!supported) return;
    recognition = new SpeechRecognition();
    recognition.lang = 'ru-RU';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      isListening = true;
      setStatus('Слушаю… Говорите, затем нажмите Готово');
      transcriptEl.textContent = '';
      resultEl.textContent = '';
    };

    recognition.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) {
          finalText += t + ' ';
        } else {
          interim += t;
        }
      }
      transcriptEl.textContent = (finalText + interim).trim();
    };

    recognition.onend = () => {
      isListening = false;
      if (cancelled) {
        close();
        return;
      }
      const text = finalText.trim();
      if (text) {
        sendToAPI(text);
      } else {
        setStatus('Ничего не распознано. Попробуйте ещё раз.');
        setTimeout(close, 2000);
      }
    };

    recognition.onerror = (e) => {
      isListening = false;
      if (e.error === 'no-speech') {
        // With continuous mode, no-speech isn't fatal — just keep going
        return;
      } else if (e.error === 'not-allowed') {
        setStatus('Нет доступа к микрофону');
        setTimeout(close, 2500);
      } else if (e.error === 'aborted') {
        // Aborted on purpose — ignore
      } else {
        setStatus(`Ошибка: ${e.error}`);
        setTimeout(close, 2000);
      }
    };
  }

  async function sendToAPI(text) {
    setStatus('Обрабатываю…');
    pulseEl.style.background = '#8B5CF6';
    doneBtn.style.display = 'none';
    cancelBtn.textContent = 'Закрыть';
    try {
      const data = await API.sendVoice(text);
      resultEl.textContent = data.message;
      setStatus('Готово');
      window.dispatchEvent(new CustomEvent('voice-added', { detail: data }));
      setTimeout(close, 2000);
    } catch (err) {
      resultEl.textContent = `Ошибка: ${err.message}`;
      setStatus('Не удалось сохранить');
      setTimeout(close, 3000);
    }
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function open() {
    if (!supported) {
      App.showToast('Голосовой ввод работает только в Chrome или Яндекс браузере');
      return;
    }
    cancelled = false;
    finalText = '';
    pulseEl.style.background = 'var(--gold)';
    resultEl.textContent = '';
    doneBtn.style.display = 'inline-block';
    cancelBtn.textContent = 'Отмена';
    overlay.classList.add('active');
    startListening();
  }

  function startListening() {
    if (!recognition) init();
    finalText = '';
    transcriptEl.textContent = '';
    try {
      recognition.start();
    } catch (e) {
      recognition.stop();
      setTimeout(() => { recognition.start(); }, 200);
    }
  }

  function close() {
    if (isListening && recognition) {
      try { recognition.stop(); } catch (_) {}
    }
    overlay.classList.remove('active');
    isListening = false;
    finalText = '';
    cancelled = false;
  }

  // "Готово" — stop and send
  doneBtn.addEventListener('click', () => {
    cancelled = false;
    if (recognition) {
      try { recognition.stop(); } catch (_) {}
    } else {
      close();
    }
  });

  // "Отмена" — discard
  cancelBtn.addEventListener('click', () => {
    cancelled = true;
    close();
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      cancelled = true;
      close();
    }
  });

  return { open, close, supported };
})();
