# Fact-check: Round 1 pitch deck sources

Checked 12 Oct 2026. No deck file was edited. Deck text checked: `deck/slides/harm.html`, `diff.html`, `app1.html`, `app3.html`, `app4.html` (same text appears in `deck-refined`, `deck-conservative`, `handoff/src/s4.py`).

---

## 1. Lok Sabha written reply, 22 Jul 2025: CONFIRMED, question number found

- **Question:** Lok Sabha **Unstarred Question No. 344**, answered 22 Jul 2025 (Ashadha 31, 1947 Saka). Title: "National Cyber Crime Reporting Portal". Asked by Shri Ajay Kumar Mandal. Answered by MoS Home Shri Bandi Sanjay Kumar.
- **Primary URL (MHA Parliament section):** https://www.mha.gov.in/MHA1/Par2017/pdfs/par2025-pdfs/LS22072025/344.pdf
  (Downloaded fine with curl, HTTP 200 PDF. Some automated fetchers get a 403, so open it in a normal browser.)
- I did not find a sansad.in annex URL for AU344. The MHA PDF is the ministry's own copy of the reply and counts as a primary source.
- **The figures match the PDF exactly:**
  - NCRP incidents: 2022 = 1029026; 2023 = 1596493 (+55.15%); **2024 = 2268346 (+42.08%)**. The table header reads "Total incidents".
  - Loss table, headed "Amount Reported (₹ In Crore)": **2023 = 7465.18; 2024 = 22845.73**. The text introduces it as "total amount of losses incurred by citizens due to cyber frauds".
- **Wording notes:** The reply calls the 22,68,346 figure "cybercrime incidents registered" on NCRP. The deck calls them "cases". That is acceptable, but "incidents" matches the source. "Lost" is a fair reading of "losses incurred", but the number is an amount *reported* through NCRP/CFCFRMS.
- **Required change:** Both `app3` and the `harm` speaker notes say the question number was not traced and cite PTI/Scroll. Replace those notes.
  - Appendix row 1, replacement text:
    > Lok Sabha Unstarred Q. No. 344, 22 Jul 2025, written reply by MoS Home Bandi Sanjay Kumar: ₹22,845.73 crore (2024) and ₹7,465.18 crore (2023) reported lost to cyber fraud; 22,68,346 cybercrime incidents on NCRP (2024). mha.gov.in/MHA1/Par2017/pdfs/par2025-pdfs/LS22072025/344.pdf
  - Harm page source line, replacement text:
    > Sources: Lok Sabha USQ 344, 22 Jul 2025; Vice, Feb 2023; ICICI, May 2015
  - Delete the note "The Lok Sabha question number was not traced; if you find it on sansad.in…". You can keep PTI via The Week (https://www.theweek.in/wire-updates/business/2025/07/22/del23-lsq-cyber-fraud.html) as a secondary source.
  - Optional: on the harm page, change "22.68 lakh cybercrime cases on NCRP" to "22.68 lakh cybercrime incidents on NCRP".

## 2. Vice/Motherboard, Joseph Cox: CONFIRMED

- Title: "How I Broke Into a Bank Account With an AI-Generated Voice". Author: **Joseph Cox**. Published **23 Feb 2023**. Bank: **Lloyds Bank** (his own account). He cloned his voice with ElevenLabs.
- The full URL works: https://www.vice.com/en/article/dy7axa/how-i-broke-into-a-bank-account-with-an-ai-generated-voice
- No change needed. Optional: use the full URL rather than `vice.com/en/article/dy7axa`.

## 3. ICICI Bank voice recognition press release: CONFIRMED

- Title: "ICICI Bank introduces voice recognition for biometric authentication". Dated **25 May 2015**.
- The URL works: https://www.icici.bank.in/about-us/news-room/2015/news-icici-bank-introduces-voice-recognition-for-biometric-authentication
- The release describes the service as authenticating customers by speech for call-centre banking. That matches the deck's "voice recognition for call-centre banking".
- No change needed.

## 4. XTTS-v2 licence: CONFIRMED CPML, but there is a risk; a fallback is recommended

**Facts**
- XTTS-v2 weights: the Hugging Face model card says "licensed under Coqui Public Model License" (https://huggingface.co/coqui/XTTS-v2). Full text: **CPML 1.0.0**, https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt. The canonical URL https://coqui.ai/cpml now returns 404. The Coqui TTS *code* is MPL-2.0. Only the weights are under CPML.
- CPML allows only "non-commercial use of a machine learning model and its outputs". The non-commercial purposes it lists include:
  - personal "research, experiment, and testing for the benefit of public knowledge"
  - use by companies "for testing, evaluation, or non-commercial research and development"
- Every one of these is limited by "only so far as you do not receive any direct or indirect payment arising from the use of the model or its output". The licence also says "Use of the model to train other models for commercial use is not a non-commercial purpose." It excludes "revenue-generating activity", and outputs carry a notice obligation: anyone you give clips to must also get the CPML terms or URL.
- **Coqui no longer exists to sell a commercial licence.** Coqui Inc. wound down in late Dec 2023 / Jan 2024. Users reported that coqui.ai said "Coqui is shutting down" (https://github.com/coqui-ai/TTS/discussions/3489). The domain now 404s. The original repo is unmaintained, and the community fork is idiap/coqui-ai-TTS (code only, weights still CPML). In practice no commercial licence can be obtained.

**Does a student hackathon prototype fit?** Probably yes, but it is not clean.
- Generating test clones of consenting team members to evaluate a detector fits "research, experiment, and testing".
- Two risks remain. (a) Prize money could be argued to be "indirect payment arising from" use of the outputs. (b) If the detector is trained or fine-tuned on XTTS clips and the pitch frames a bank deployment path, the "train other models for commercial use" clause applies.
- This is a judgement call, not legal advice. Keep XTTS to evaluation-only test clips, do not train on them, and say so in the deck.

**RAKSHAM / Amazon terms:** I found no official rules page, IP clause or third-party-licence clause publicly. Only secondary listings turned up, e.g. https://www.startupgrantsindia.com/competitions/raksham-ai-cybersecurity-hackathon and https://educationpost.in/news/education/iit-delhi-i4c-and-amazon-launch-ai-hackathon-to-develop-solutions-against-deepfakes-and-cyber-fraud. These list organisers ARIES + DevClub IIT Delhi, Amazon, and I4C, and say judging includes "responsible use of AI". Check the registration portal or rulebook, or ask the organisers.

**Fallback options (licences verified on the repos)**
| Tool | Code | Weights | Verdict |
|---|---|---|---|
| OpenVoice V1/V2 (github.com/myshell-ai/OpenVoice) | MIT | MIT. Repo: "Starting from April 2024, both V2 and V1 are released under MIT License." | **Best fallback.** Zero-shot cloning, commercial use allowed |
| RVC WebUI (github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) | MIT | Base model trained on VCTK, which is CC-BY 4.0 | Good second generator (voice conversion) |
| StyleTTS2 (github.com/yl4579/StyleTTS2) | MIT | Pretrained models carry a condition: tell listeners speech is synthesized unless you have permission for the voice | Usable. Consent covers it |
| F5-TTS (github.com/SWivid/F5-TTS) | MIT | **CC-BY-NC** (Emilia training data) | Same non-commercial problem as XTTS; avoid as the main generator |

**Suggested replacement text for the Appendix A "Clone generators" row (app1):**
> Clone generators: OpenVoice V2 (MIT) and RVC voice conversion (MIT); XTTS-v2 (Coqui Public Model License, non-commercial) only for held-out evaluation clips, never for training. Test clones of consenting team members, research use only.

## 5. Pindrop Pulse claims: CONFIRMED, with a precision note

- Cited URL: https://www.pindrop.com/article/pindrop-pulse-for-audio-deepfake-detection/ by Amit Gupta, SVP Product Management, dated 20 Feb 2024.
- Exact wording on that page: "99% detection rate for known deepfake engines" and "over 90% detection for new or unseen deepfake generation engines". It repeats this as "90% of 'zero-day' attacks".
- The deck says "99% on known engines and over 90% on unseen ones" and "vendor claims, not tested by us". That is accurate. No change needed.
- Optional: this is a 2024 vendor blog post, not a product page. On `diff`, "Its page claims" is fine. For an exact attribution, write "Pindrop's Feb 2024 launch post claims…".
