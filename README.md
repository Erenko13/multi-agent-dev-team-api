# Multi-Agent Dev Team API

> Detaylı bilgi için: [README2.md](README2.md) · [ARCHITECTURE.md](ARCHITECTURE.md) Frontend için: [multi-agent-dev-team-fe](https://github.com/Erenko13/multi-agent-dev-team-fe)

## 1. Amaç

Yarışmanın başlarında potansiyel fikirleri düşünürken aklıma devreye alım agent'ı, devops agent'ı, tester agent'ı ve DBA agent'ı gibi Turkcell'deki SDLC'nin çeşitli adımlarını iyileştiren/hızlandıran sistemler yapmayı düşündüm. Daha sonra neden direkt tüm süreci yönetip developer'lara takım arkadaşı olabilecek bütüncül bir sistem olmasın ki, dedim. Fikrimi bulduktan sonra benzer toolları araştırdım, özellikle prompt üzerinden yazılım ürünü geliştiren Lovable gibi ürünleri inceledim. Bunların o kadar da complex olmayan, hızlıca geliştirilebilecek ürünler olduğunu gördüm ve bizim developer'larımızda neden olmasın diyerek kodlamaya başladım.

## 2. Tech Stack

- **a) Core Framework:** LangGraph (StateGraph orkestrasyonu) + FastAPI (REST API), request/response şemaları için Pydantic ve gerçek zamanlı akış için Server-Sent Events (SSE).
- **b) Dil ve Runtime:** Python 3.12+, ASGI server olarak uvicorn.
- **c) LLM Sağlayıcılar (multi-provider strategy):**
  - Groq — Llama 3.1 8B (PM agent) and Llama 3.3 70B (Architect)
  - Google Gemini 2.5 Flash — Supervisor, Developer, Reviewer, Tester
  - Mistral Codestral 2508 — Developer (code-specialized)
  - Optional: Cerebras (Qwen 3 235B), Ollama (local), or any OpenAI-compatible endpoint
- **d) Sandbox (İzole Çalışma Ortamı):** Docker konteynerleri — Python 3.12 + Node.js 20 kurulu, çıktı dizinine bağlı, 2 CPU / 2GB RAM sınırlamasıyla.
- **e) State & Checkpointing:** LangGraph MemorySaver (in-memory).
- **f) Konfigürasyon:** YAML içerisinde (`config.yaml`) provider/agent atamaları bulunuyor, `.env` içerisinde API key'ler tutuluyor.
- **g) Altyapı:** 8 GB RAM, 4 Core CPU, 80 GB SSD, Linux (Ubuntu 24.04).

## 3. Mimari

Temelde AI agent'lar, LLM'lerin kontrol ettiği ve tool kullanabilen yapılardır. Agent projesi geliştirmek için CrewAI, AutoGen veya LlamaIndex gibi kütüphaneler de kullanılabilirdi, fakat LangGraph gerek sağladığı tool'lar ve entegrasyonlarla gerekse verdiği low-level kontrol ile kolay kullanımıyla bunların arasında öne çıkıyor. Ben de bu yüzden LangGraph kullandım. LangGraph, bir agent takımını graph olarak ele alıp her bir agent'a node diyor. Bu node'ların etkileşimini, durumlarını, tool'larını ve kontrolü sağlayan LLM'leri kendimiz ayarlıyoruz. Her node için bir LLM instance'ı oluşturuluyor ve o agent'ın görevine uygun bir prompt veriliyor. Daha sonra bu graph, chat arayüzünden aldığı kullanıcı prompt'larıyla ve onaylarla sequential olarak çalışıyor.

Bu projede agent takımı, chat arayüzünden gelen development isteğine bağlı olarak bir proje tasarlayıp oluşturup test ve review ederek çalıştırıyor ve kullanıma hazır hale getiriyor. Bunu yaparken sunucuda önceden ayrılmış olan 5 farklı proje klasöründe kod dosyalarını oluşturup Docker container'ında bu proje için gerekli kurulumları yaptıktan sonra çalıştırıyor. En son olarak da kullanıcıya çalışan ürünün URL'sini veriyor.

- **a)** LangGraph üzerine kurulu 6 agent'lı bir pipeline (PM → Architect → Supervisor → Developer → Reviewer → Tester); routing kararları için LLM kullanılmıyor, conditional graph edge'leri ile deterministik routing yapılıyor. Sequential graph mimarisi kullandım; ideal senaryoda supervisor mimarisi (routing'in ayrı bir LLM tarafından yapıldığı mimari) daha faydalı olabilirdi, fakat fazladan model eklemek API sınırlarını daha da zorlayacaktı.
- **b)** AgentState'leri tutmak için ortak bir TypedDict var, tüm node'lar onu kullanıyor; her agent yalnızca kendi slice'ını okur ve oraya durumunu yazar, agent'lar arası doğrudan iletişim olmuyor. LangGraph zaten TypedDict kullandığı için karmaşıklığı artırmamak adına önerilen çözümü kullandım.
- **c)** LangGraph'ın `interrupt()` mekanizmasıyla iki insan onay checkpoint'i bulunuyor: architecture agent tasarımı yaptıktan sonra ve final output'tan sonra, chat arayüzündeki onay veya feedback butonu ile graph'ın istenen sonuca ulaşana kadar tekrarlı çalışması sağlanabiliyor. Human-in-the-loop yaklaşımı, kod yazmak/planlamak gibi teknik işler için neredeyse şart olduğundan bu onay mekanizmasını ekledim.
- **d)** Multi-provider LLM stratejisi yükü ücretsiz tier'lar arasında dağıtır: Groq (PM + Architect), Mistral Codestral (Developer), Gemini 2.5 Flash (Developer, Supervisor, Reviewer, Tester). Bu projede tüm süreci en çok zorlayan konu, modellerin token ve request limitleri oldu. Bolca kaynak mühendisliği yaparak hem bu limitleri verimli şekilde kullanmaya hem de model performansını düşürmeden context window'ları uygun olacak şekilde, agent görevine uygun bir model seçmeye çalıştım.
- **e)** Agent koduna dokunulmadan FastAPI REST + SSE katmanı eklendi. Beş proje dosyası eş zamanlı düzenlenebilir; event loop'u serbest tutmak için pipeline `asyncio.to_thread()` üzerinden çalışır.
- **f)** Her node'dan sonra MemorySaver ile checkpoint kaydedilir. Bu; hata kurtarma, loop state koruması ve human-in-the-loop resumption'ı mümkün kılar.
- **g)** Token ve request israfını önlemek, deadlock oluşumundan kaçınmak için Developer–Reviewer loop en fazla 3 iterasyon ile sınırlandırıldı. Tüm file tool'ları workspace'te sandbox altında bulunuyor (path traversal, search tool içinde engellendi). Shell komutları bir allowlist kullanır.
- **h)** Agent'ların sunucudaki diğer dosyaları ve kurulumları bozmaması için Docker kullanmaları sağlandı. Docker sandbox, shell komutlarını (`pip`, `npm`, `pytest`) host'tan izole eder; agent kodu host'ta kalır, yalnızca shell exec container'a gönderilir (2 Core CPU / 2 GB RAM).

## 4. Sonuç

Multi Agent Dev Team projesi ile developer'lara her geliştirmede yardım edebilecek bir sistem ortaya çıktı; artık çeşitli denemeler, basit task'lar ve kişisel uygulamalar için zaman harcamalarına gerek kalmaz. Halihazırda var olan uygulamalardaki geliştirmeler için de VS Code'daki AI Toolkit eklentisi ile Multi Agent Dev Team'e bağlantı kurularak VS Code içerisinden kullanıldığı bir senaryoda yine geliştirme sürecini ciddi şekilde hızlandıracaktır. Sonuç olarak Multi Agent Dev Team, developer'larımıza her task'ı yapabilen ikinci bir beyin gibi çalışan bir sistem olarak hizmet edecektir.

## 5. Sonraki Adımlar

Herhangi bir ücretli API'dan LLM'ler eklenerek şu anda projenin darboğazı olan token ve request limitlerinin aşılması sağlanabilir. OpenAI veya Anthropic API'ları eklenerek daha güçlü modellerle agent'lar daha etkili hale getirilebilir. Şirketin kendi GPU sunucularında lokalde güçlü modeller çalıştırılarak agent'ların performansı artırılabilir. Bu yapılırsa başka faydaları da olacaktır: agent response süresi kısalır, dış API maliyetleri ortadan kalkar ve projelerin dışarıya görünmesinden kaynaklı güvenlik açığı oluşmaz.

Sequential'dan Supervisor mimariye çevirilerek daha güçlü bir modelin yardımıyla graph'ın çalışması sağlanarak çıktının performansı arttırılabilir.

Agent state'leri ve graph checkpoint'lerini kaydetmek için LangGraph içinde halihazırda bulunan SQLite desteği eklenerek bu verilerin diskte tutulması sağlanabilir.

Daha fazla agent eklenerek paralelde birden fazla, hatta sürü halinde agent'lardan oluşan development ekiplerinin çalışması sağlanabilir.

## 6. Kapanış

Bu projeyi yaparken hem çok şey öğrendim hem de çok keyif aldım. Agent'ların gücünü deneyerek ve faydalı bir ürün geliştirerek de görmüş oldum. Ancak her şey çok hızlı gelişiyor; sürekli yeni ürünler ve teknolojiler çıkıyor, kullandığım kaynakların çoğu 3 ay önce yoktu bile. Hatta bu yarışma süresinde Anthropic şirketi "Claude Managed Agents" özelliğini duyurdu ve yine kendi "prompt to software" ürünlerinin çıkacağı sızdırıldı. İleride herkes bunları kullanarak anında kendi agent'larını ayağa kaldırıp iş yaptırabilir olacak; fakat API maliyetlerinin artacağı, abonelik sistemiyle alınan modellerin kalitesinin belirsiz olduğu ve hatta azalabildiği için, API verisinin güvenliği hakkında soru işaretleri olduğu ve prompt'larda tam özgürlük sağlamadıkları için kendi Multi Agent Dev Team projem veya Turkcell'in Teknocan'ı gibi özel geliştirilmiş ve kendi sunucularımızda çalışan sistemlerin önemi daha da artacaktır.

## Faydalandığım Kaynaklar

- https://magazine.sebastianraschka.com/p/components-of-a-coding-agent
- https://github.com/cheahjs/free-llm-api-resources
- https://reference.langchain.com/python/langgraph-supervisor
- https://reference.langchain.com/python/langgraph
- https://docs.langchain.com/oss/python/langgraph/workflows-agents
- https://www.anthropic.com/engineering/building-effective-agents
- https://www.youtube.com/watch?v=HonlBK19F1o

> Not: Bu readme dosyası 14.04.2026 günü düzenlenmiştir, diğer tüm dosyalar yarışma çıktısının teslim anındaki gibidir.

---

## License

See [LICENSE](LICENSE).
