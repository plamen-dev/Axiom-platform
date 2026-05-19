using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Axiom.Core.Capabilities;
using Newtonsoft.Json;

namespace Axiom.Core.Bridge
{
    /// <summary>
    /// Named pipe server that runs inside Revit.
    /// Listens for JSON-RPC requests from the Python orchestrator,
    /// dispatches to the appropriate IAxiomCapability, and returns results.
    ///
    /// All Revit API calls are marshalled onto the main thread via
    /// ExternalEvent to satisfy Revit's threading requirements.
    /// </summary>
    public class AxiomPipeServer : IDisposable
    {
        public const string DefaultPipeName = "axiom";

        private readonly ToolRegistry _registry;
        private readonly string _pipeName;
        private CancellationTokenSource _cts;
        private Task _listenTask;

        // Revit thread marshalling
        private ExternalEvent _externalEvent;
        private AxiomExternalEventHandler _eventHandler;

        public AxiomPipeServer(
            ToolRegistry registry,
            string pipeName = DefaultPipeName)
        {
            _registry = registry;
            _pipeName = pipeName;
        }

        /// <summary>
        /// Start listening for pipe connections in a background thread.
        /// Must be called from Revit main thread (OnStartup or Idling handler).
        ///
        /// Does NOT require UIApplication — ExternalEvent.Create() works
        /// with UIControlledApplication context. The UIApplication instance
        /// is received later via AxiomExternalEventHandler.Execute(UIApplication)
        /// when Revit fires the event on its main thread.
        /// </summary>
        public void Start()
        {
            _eventHandler = new AxiomExternalEventHandler();
            _externalEvent = ExternalEvent.Create(_eventHandler);

            _cts = new CancellationTokenSource();
            _listenTask = Task.Run(() => ListenLoop(_cts.Token));
        }

        public void Stop()
        {
            _cts?.Cancel();
            try { _listenTask?.Wait(TimeSpan.FromSeconds(3)); }
            catch { /* shutting down */ }
        }

        private void ListenLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    using (var pipe = new NamedPipeServerStream(
                        _pipeName,
                        PipeDirection.InOut,
                        1,
                        PipeTransmissionMode.Byte,
                        PipeOptions.Asynchronous))
                    {
                        pipe.WaitForConnection();

                        string requestJson = ReadMessage(pipe);
                        if (string.IsNullOrEmpty(requestJson))
                            continue;

                        string responseJson;
                        try
                        {
                            responseJson = HandleRequest(requestJson);
                        }
                        catch (Exception ex)
                        {
                            System.Diagnostics.Debug.WriteLine(
                                $"[AxiomPipeServer] HandleRequest error: {ex}");
                            responseJson = JsonConvert.SerializeObject(new PipeResponse
                            {
                                Id = "unknown",
                                Error = new PipeResponseError
                                {
                                    Code = -32603,
                                    Message = $"Internal server error: {ex.Message}"
                                }
                            });
                        }

                        WriteMessage(pipe, responseJson);
                        pipe.Flush();
                        pipe.WaitForPipeDrain();
                    }
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    System.Diagnostics.Debug.WriteLine(
                        $"[AxiomPipeServer] ListenLoop error: {ex.Message}");
                }
            }
        }

        private string HandleRequest(string requestJson)
        {
            PipeRequest request;
            try
            {
                request = JsonConvert.DeserializeObject<PipeRequest>(requestJson);
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new PipeResponse
                {
                    Id = "unknown",
                    Error = new PipeResponseError
                    {
                        Code = -32700,
                        Message = $"Parse error: {ex.Message}"
                    }
                });
            }

            if (request.Method != "execute_tool")
            {
                return JsonConvert.SerializeObject(new PipeResponse
                {
                    Id = request.Id,
                    Error = new PipeResponseError
                    {
                        Code = -32601,
                        Message = $"Unknown method: {request.Method}"
                    }
                });
            }

            if (!_registry.TryGet(request.Params.ToolName, out IAxiomCapability capability))
            {
                return JsonConvert.SerializeObject(new PipeResponse
                {
                    Id = request.Id,
                    Error = new PipeResponseError
                    {
                        Code = -32602,
                        Message = $"Unknown capability: {request.Params.ToolName}"
                    }
                });
            }

            // Execute on Revit main thread via ExternalEvent
            CapabilityResult capResult = null;
            var waitHandle = new ManualResetEventSlim(false);

            _eventHandler.SetWork((uiApp) =>
            {
                Document doc = uiApp.ActiveUIDocument?.Document;
                if (doc == null)
                {
                    capResult = new CapabilityResult
                    {
                        Status = "FAILED",
                        Errors = { "No active Revit document." }
                    };
                    waitHandle.Set();
                    return;
                }

                string txName = request.Params.TransactionName
                    ?? $"Axiom_{capability.Name}";

                if (request.Params.Simulate)
                {
                    capResult = capability.Execute(doc, request.Params.ArgsJson, true);
                    waitHandle.Set();
                    return;
                }

                using (Transaction tx = new Transaction(doc, txName))
                {
                    try
                    {
                        tx.Start();
                        capResult = capability.Execute(
                            doc, request.Params.ArgsJson, false);

                        if (capResult.Status == "FAILED")
                            tx.RollBack();
                        else
                            tx.Commit();
                    }
                    catch (Exception ex)
                    {
                        if (tx.HasStarted())
                            tx.RollBack();

                        capResult = new CapabilityResult
                        {
                            Status = "FAILED",
                            Errors = { ex.Message }
                        };
                    }
                }

                waitHandle.Set();
            });

            _externalEvent.Raise();
            waitHandle.Wait(TimeSpan.FromSeconds(120));

            if (capResult == null)
            {
                return JsonConvert.SerializeObject(new PipeResponse
                {
                    Id = request.Id,
                    Error = new PipeResponseError
                    {
                        Code = -32000,
                        Message = "Execution timed out or was not processed."
                    }
                });
            }

            return JsonConvert.SerializeObject(new PipeResponse
            {
                Id = request.Id,
                Result = new PipeResponseResult
                {
                    Status = capResult.Status,
                    CreatedIds = capResult.CreatedIds,
                    Warnings = capResult.Warnings,
                    Errors = capResult.Errors,
                    DurationMs = capResult.DurationMs,
                    OutputData = capResult.OutputData
                }
            });
        }

        private static string ReadMessage(NamedPipeServerStream pipe)
        {
            byte[] lengthBytes = new byte[4];
            int read = pipe.Read(lengthBytes, 0, 4);
            if (read < 4) return null;

            int length = BitConverter.ToInt32(lengthBytes, 0);
            if (length <= 0 || length > 10_000_000) return null;

            byte[] buffer = new byte[length];
            int totalRead = 0;
            while (totalRead < length)
            {
                int chunk = pipe.Read(buffer, totalRead, length - totalRead);
                if (chunk == 0) break;
                totalRead += chunk;
            }

            return Encoding.UTF8.GetString(buffer, 0, totalRead);
        }

        private static void WriteMessage(NamedPipeServerStream pipe, string message)
        {
            byte[] payload = Encoding.UTF8.GetBytes(message);
            byte[] lengthBytes = BitConverter.GetBytes(payload.Length);
            pipe.Write(lengthBytes, 0, 4);
            pipe.Write(payload, 0, payload.Length);
        }

        public void Dispose()
        {
            Stop();
            _externalEvent?.Dispose();
        }
    }

    /// <summary>
    /// IExternalEventHandler that bridges pipe requests onto the Revit main thread.
    /// </summary>
    public class AxiomExternalEventHandler : IExternalEventHandler
    {
        private Action<UIApplication> _pendingWork;
        private readonly object _lock = new object();

        public void SetWork(Action<UIApplication> work)
        {
            lock (_lock)
            {
                _pendingWork = work;
            }
        }

        public void Execute(UIApplication app)
        {
            Action<UIApplication> work;
            lock (_lock)
            {
                work = _pendingWork;
                _pendingWork = null;
            }

            work?.Invoke(app);
        }

        public string GetName() => "AxiomPipeBridgeHandler";
    }
}
