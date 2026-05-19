using Autodesk.Revit.UI;
using System;
using System.Linq;
using System.Reflection;

namespace Axiom.RevitAddin
{
    public class App : IExternalApplication
    {
        private Axiom.Core.Bridge.AxiomPipeServer _pipeServer;
        private static Axiom.Core.Bridge.ToolRegistry _registry;

        /// <summary>
        /// Returns the shared capability registry initialized at startup.
        /// Used by PromptCommand to dispatch free-text prompts.
        /// </summary>
        public static Axiom.Core.Bridge.ToolRegistry GetRegistry()
        {
            return _registry;
        }

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                const string tabName = "Axiom";
                const string panelName = "General";

                // IMPORTANT:
                // This internal name must be NEW and UNIQUE
                const string buttonInternalName = "Axiom_Prompt_Button_V3";
                const string buttonText = "Prompt";

                // -----------------------------
                // Create tab (safe if exists)
                // -----------------------------
                try
                {
                    application.CreateRibbonTab(tabName);
                }
                catch
                {
                    // Tab already exists - ignore
                }

                // -----------------------------
                // Get or create panel
                // -----------------------------
                RibbonPanel panel =
                    application.GetRibbonPanels(tabName)
                               .FirstOrDefault(p => p.Name == panelName)
                    ?? application.CreateRibbonPanel(tabName, panelName);

                // -----------------------------
                // Check if button already exists
                // -----------------------------
                bool buttonExists = panel.GetItems()
                    .OfType<PushButton>()
                    .Any(b => b.Name == buttonInternalName);

                if (!buttonExists)
                {
                    string assemblyPath = Assembly.GetExecutingAssembly().Location;

                    PushButtonData btnData = new PushButtonData(
                        buttonInternalName,
                        buttonText,
                        assemblyPath,
                        "Axiom.RevitAddin.PromptCommand"
                    );

                    panel.AddItem(btnData);
                }

                // -----------------------------
                // Initialize capability registry
                // -----------------------------
                _registry = new Axiom.Core.Bridge.ToolRegistry();
                _registry.Register(new Axiom.RevitAddin.Capabilities.GridCapability());
                _registry.Register(new Axiom.RevitAddin.Capabilities.LevelCapability());
                _registry.Register(new Axiom.RevitAddin.Capabilities.InventoryModelCapability());

                // -----------------------------
                // Start Axiom pipe bridge
                // -----------------------------
                _pipeServer = new Axiom.Core.Bridge.AxiomPipeServer(_registry);
                _pipeServer.Start();

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Axiom Startup Error", ex.ToString());
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            _pipeServer?.Stop();
            return Result.Succeeded;
        }
    }
}
