using System.Collections.Generic;
using Newtonsoft.Json;

namespace Axiom.Core.Bridge
{
    /// <summary>
    /// JSON-RPC 2.0 request received from the Python orchestrator.
    /// Property names use [JsonProperty] to match the snake_case JSON keys
    /// sent by the Python PipeClient.
    /// </summary>
    public class PipeRequest
    {
        [JsonProperty("jsonrpc")]
        public string Jsonrpc { get; set; } = "2.0";

        [JsonProperty("id")]
        public string Id { get; set; }

        [JsonProperty("method")]
        public string Method { get; set; }

        [JsonProperty("params")]
        public PipeRequestParams Params { get; set; }
    }

    public class PipeRequestParams
    {
        [JsonProperty("tool_name")]
        public string ToolName { get; set; }

        [JsonProperty("args_json")]
        public string ArgsJson { get; set; }

        [JsonProperty("simulate")]
        public bool Simulate { get; set; }

        [JsonProperty("transaction_name")]
        public string TransactionName { get; set; }
    }

    /// <summary>
    /// JSON-RPC 2.0 response sent back to the Python orchestrator.
    /// Property names use [JsonProperty] to produce the snake_case JSON keys
    /// that the Python PipeClient expects.
    /// </summary>
    public class PipeResponse
    {
        [JsonProperty("jsonrpc")]
        public string Jsonrpc { get; set; } = "2.0";

        [JsonProperty("id")]
        public string Id { get; set; }

        [JsonProperty("result")]
        public PipeResponseResult Result { get; set; }

        [JsonProperty("error")]
        public PipeResponseError Error { get; set; }
    }

    public class PipeResponseResult
    {
        [JsonProperty("status")]
        public string Status { get; set; }

        [JsonProperty("created_ids")]
        public List<string> CreatedIds { get; set; } = new List<string>();

        [JsonProperty("warnings")]
        public List<string> Warnings { get; set; } = new List<string>();

        [JsonProperty("errors")]
        public List<string> Errors { get; set; } = new List<string>();

        [JsonProperty("duration_ms")]
        public long DurationMs { get; set; }

        [JsonProperty("output_data")]
        public Dictionary<string, object> OutputData { get; set; }
            = new Dictionary<string, object>();
    }

    public class PipeResponseError
    {
        [JsonProperty("code")]
        public int Code { get; set; }

        [JsonProperty("message")]
        public string Message { get; set; }
    }
}
