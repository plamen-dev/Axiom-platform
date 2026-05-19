using Autodesk.Revit.DB;
using Axiom.Core.Models;
using System;
using System.Linq;

namespace Axiom.RevitAddin.Services
{
    /// <summary>
    /// Service responsible for creating a full grid layout
    /// with locked growth direction rules.
    ///
    /// Supports both uniform spacing (SpacingFeet) and variable
    /// per-bay spacing (HorizontalSpacingsFeet / VerticalSpacingsFeet).
    /// </summary>
    public class GridCreationService
    {
        // ----------------------------
        // GROWTH DIRECTION RULES (T19)
        // ----------------------------
        // Numeric grids must grow to the RIGHT (+X)
        private const double NumericGrowthDirectionX = 1.0;

        // Alphabetic grids must grow DOWN (-Y)
        private const double AlphabeticGrowthDirectionY = -1.0;

        public void CreateHorizontalGrids(Document doc, GridParameters parameters)
        {
            // ----------------------------
            // DERIVED DEFAULTS (preserved)
            // ----------------------------
            if (string.IsNullOrWhiteSpace(parameters.Naming))
            {
                parameters.Naming = "Numeric";
            }

            // Compute cumulative offsets for variable spacing
            double[] hOffsets = BuildOffsets(
                parameters.HorizontalCount,
                parameters.HorizontalSpacingsFeet,
                parameters.SpacingFeet);
            double[] vOffsets = BuildOffsets(
                parameters.VerticalCount,
                parameters.VerticalSpacingsFeet,
                parameters.SpacingFeet);

            double hSpan = hOffsets.Length > 1 ? hOffsets[hOffsets.Length - 1] : 0;
            double vSpan = vOffsets.Length > 1 ? vOffsets[vOffsets.Length - 1] : 0;

            if (parameters.Length <= 0)
            {
                parameters.Length = hSpan + 20.0;
            }

            // ----------------------------
            // A/1 ANCHOR at project origin (0,0,0)
            // Grid 1 at X=0, Grid A at Y=0.
            // Tails extend into negative space (left of 1, above A).
            // ----------------------------
            XYZ origin = XYZ.Zero;

            // ----------------------------
            // SHARED EXTENT RULES (T18 preserved)
            // ----------------------------
            double shortTail = 10.0;

            // When both orientations are present, line length is derived from
            // the other direction's span. When only one orientation is requested,
            // use the explicit Length parameter for line extent.
            double fullWidth = hSpan > 0
                ? hSpan
                : Math.Max(parameters.Length - shortTail, shortTail);

            double fullHeight = vSpan > 0
                ? vSpan
                : Math.Max(parameters.Length - shortTail, shortTail);

            double xStartShort = -shortTail;
            double xEndFull = fullWidth;

            double yStartFull = -fullHeight;
            double yEndShort = shortTail;

            // ----------------------------
            // NUMERIC GRIDS (1,2,3...)
            // Vertical lines spaced along X, growing RIGHT (T19 Item 1)
            // Line drawn from top to bottom so grid head/bubble appears at top (north)
            // ----------------------------
            for (int i = 0; i < parameters.HorizontalCount; i++)
            {
                double xOffset =
                    origin.X + hOffsets[i] * NumericGrowthDirectionX;

                string gridName = (i + 1).ToString();

                Line line = Line.CreateBound(
                    new XYZ(xOffset, origin.Y + yEndShort, 0),
                    new XYZ(xOffset, origin.Y + yStartFull, 0)
                );

                Grid grid = Grid.Create(doc, line);
                grid.Name = gridName;
            }

            // ----------------------------
            // ALPHABETIC GRIDS (A,B,C...)
            // Horizontal lines spaced along Y, growing DOWN (T19 Item 2)
            // ----------------------------
            for (int i = 0; i < parameters.VerticalCount; i++)
            {
                double yOffset =
                    origin.Y + vOffsets[i] * AlphabeticGrowthDirectionY;

                string gridName = GetAlphabeticName(i);

                Line line = Line.CreateBound(
                    new XYZ(origin.X + xStartShort, yOffset, 0),
                    new XYZ(origin.X + xEndFull, yOffset, 0)
                );

                Grid grid = Grid.Create(doc, line);
                grid.Name = gridName;
            }
        }

        /// <summary>
        /// Build cumulative offset array from variable spacings or uniform spacing.
        /// Returns array of length <paramref name="count"/> where offset[0] = 0.
        /// </summary>
        private static double[] BuildOffsets(
            int count, double[] variableSpacings, double uniformSpacing)
        {
            if (count <= 0)
                return new double[] { 0 };

            double[] offsets = new double[count];
            offsets[0] = 0;

            if (variableSpacings != null && variableSpacings.Length > 0)
            {
                for (int i = 1; i < count; i++)
                {
                    offsets[i] = offsets[i - 1] + variableSpacings[i - 1];
                }
            }
            else
            {
                for (int i = 1; i < count; i++)
                {
                    offsets[i] = i * uniformSpacing;
                }
            }

            return offsets;
        }

        private string GetAlphabeticName(int index)
        {
            string name = string.Empty;
            index++;

            while (index > 0)
            {
                int remainder = (index - 1) % 26;
                name = (char)('A' + remainder) + name;
                index = (index - 1) / 26;
            }

            return name;
        }
    }
}
