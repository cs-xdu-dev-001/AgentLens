export const providerCards = [
  { key: "deepseek", name: "DeepSeek" },
  { key: "mimo", name: "MiMo" },
  { key: "openai", name: "OpenAI" },
  { key: "siliconflow", name: "SiliconFlow" },
  { key: "zhipu", name: "智谱AI" },
  { key: "bailian", name: "百炼" },
  { key: "custom", name: "自定义" },
];

export const providerPresets = {
  deepseek: {
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    models: [
      { label: "deepseek-v4-flash", name: "DeepSeek V4 Flash", modelType: "chat", modelName: "deepseek-v4-flash", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "deepseek-v4-pro", name: "DeepSeek V4 Pro", modelType: "chat", modelName: "deepseek-v4-pro", temperature: "0.6", topP: "0.9", maxTokens: "4096" },
    ],
  },
  mimo: {
    label: "MiMo",
    baseUrl: "https://api.xiaomimimo.com/v1",
    models: [
      { label: "mimo-v2.5-pro", name: "MiMo V2.5 Pro", modelType: "chat", modelName: "mimo-v2.5-pro", temperature: "1.0", topP: "0.95", maxTokens: "4096" },
    ],
  },
  openai: {
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    models: [
      { label: "gpt-5.6-sol", name: "GPT-5.6 Sol", modelType: "chat", apiMode: "responses", modelName: "gpt-5.6-sol", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "gpt-5.6-terra", name: "GPT-5.6 Terra", modelType: "chat", apiMode: "responses", modelName: "gpt-5.6-terra", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "gpt-5.6-luna", name: "GPT-5.6 Luna", modelType: "chat", apiMode: "responses", modelName: "gpt-5.6-luna", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "text-embedding-3-small", name: "Text 向量化 3 Small", modelType: "embedding", modelName: "text-embedding-3-small", temperature: "", topP: "", maxTokens: "" },
      { label: "text-embedding-3-large", name: "Text 向量化 3 Large", modelType: "embedding", modelName: "text-embedding-3-large", temperature: "", topP: "", maxTokens: "" },
    ],
  },
  siliconflow: {
    label: "SiliconFlow",
    baseUrl: "https://api.siliconflow.cn/v1",
    models: [
      { label: "deepseek-ai/DeepSeek-V4-Pro", name: "DeepSeek V4 Pro", modelType: "chat", modelName: "deepseek-ai/DeepSeek-V4-Pro", temperature: "0.6", topP: "0.9", maxTokens: "4096" },
      { label: "deepseek-ai/DeepSeek-V4-Flash", name: "DeepSeek V4 Flash", modelType: "chat", modelName: "deepseek-ai/DeepSeek-V4-Flash", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "zai-org/GLM-5.2", name: "GLM-5.2", modelType: "chat", modelName: "zai-org/GLM-5.2", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "BAAI/bge-m3", name: "BGE M3 向量化", modelType: "embedding", modelName: "BAAI/bge-m3", temperature: "", topP: "", maxTokens: "" },
    ],
  },
  zhipu: {
    label: "Zhipu AI",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    models: [
      { label: "glm-5.2", name: "GLM-5.2", modelType: "chat", modelName: "glm-5.2", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "glm-5-turbo", name: "GLM-5 Turbo", modelType: "chat", modelName: "glm-5-turbo", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "glm-4.7", name: "GLM-4.7", modelType: "chat", modelName: "glm-4.7", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
    ],
  },
  bailian: {
    label: "Bailian",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: [
      { label: "qwen3.7-max", name: "Qwen3.7 Max", modelType: "chat", modelName: "qwen3.7-max", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "qwen3.7-plus", name: "Qwen3.7 Plus", modelType: "chat", modelName: "qwen3.7-plus", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "qwen3.6-plus", name: "Qwen3.6 Plus", modelType: "chat", modelName: "qwen3.6-plus", temperature: "0.7", topP: "0.9", maxTokens: "4096" },
      { label: "text-embedding-v4", name: "Bailian 向量化 V4", modelType: "embedding", modelName: "text-embedding-v4", temperature: "", topP: "", maxTokens: "" },
    ],
  },
  custom: {
    label: "Custom API",
    baseUrl: "",
    models: [],
  },
};
