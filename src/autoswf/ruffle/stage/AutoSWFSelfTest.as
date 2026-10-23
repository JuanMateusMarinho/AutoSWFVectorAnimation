package {
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.geom.Matrix;

    /** The stage's self-test (flashvar selftest=1). Each check is traced as
     *  "AUTOSWF CHECK <name> | <PASS | FAIL detail | SKIP why>", then "AUTOSWF DONE"; tests/ruffle_selftest.py reads
     *  them from Ruffle's output. Steps run one per frame and wait for the stage where they must. */
    public class AutoSWFSelfTest {
        private var stage:AutoSWFStage;
        private var steps:Array = [];
        private var waited:int = 0;

        public function AutoSWFSelfTest(stage:AutoSWFStage) {
            this.stage = stage;
        }

        public function start():void {
            steps.push(wait(2), checkSetup, playSkill, waitSkill, waitIdle, done);
            stage.addEventListener(Event.ENTER_FRAME, onFrame);
        }

        private function onFrame(e:Event):void {
            while (steps.length > 0) {
                var finished:Boolean = steps[0]();
                if (!finished) return;
                steps.shift();
                waited = 0;
            }
            stage.removeEventListener(Event.ENTER_FRAME, onFrame);
        }

        private function check(name:String, ok:Boolean, detail:String = ""):void {
            stage.log("CHECK " + name + " | " + (ok ? "PASS" : "FAIL " + detail));
        }

        private function skip(name:String, why:String):void {
            stage.log("CHECK " + name + " | SKIP " + why);
        }

        private function wait(frames:int):Function {
            return function ():Boolean { return ++waited >= frames; };
        }

        private function row(name:String):Object {
            for each (var r:Object in stage.settings.labels) {
                if (r.name == name) return r;
            }
            return null;
        }

        private function idleAnimation():String {
            var r:Object = row("Idle");
            return r == null ? null : r.armor[stage.gender];
        }

        private function checkSetup():Boolean {
            var count:int = 0;
            for (var label:String in stage.avatar.animEvents) count++;
            check("listeners", count > 0, "the armor registered no game label");
            var idle:String = idleAnimation();
            var face:MovieClip = stage.face;
            if (idle == null) skip("idle", "the armor does not take Idle");
            else check("idle", face != null && face.currentLabel == idle, face == null ? "no head" : face.currentLabel);
            if (face == null || face.transform.matrix.a == 1 && face.transform.matrix.d == 1 &&
                    face.transform.matrix.tx == 0 && face.transform.matrix.ty == 0) {
                skip("anchored", "the armor does not anchor itself");
            } else {
                var m:Matrix = face.transform.matrix.clone();
                m.concat(stage.avatar.mcChar.head.transform.matrix);
                var near:Function = function (a:Number, b:Number, by:Number):Boolean { return Math.abs(a - b) < by; };
                // positions are kept in twips (1/20 px) by the player
                check("anchored", near(m.a, 1, 0.01) && near(m.b, 0, 0.01) && near(m.c, 0, 0.01) &&
                    near(m.d, 1, 0.01) && near(m.tx, 0, 0.1) && near(m.ty, 0, 0.1), m.toString());
            }
            check("hair hidden", !stage.avatar.mcChar.head.hair.visible, "the avatar's hair still shows");
            var probe:MovieClip = new MovieClip();
            var before:uint = uint(stage.colors.Hair);
            stage.mcSetColor(probe, "Hair", "None");
            stage.setPlayerColor("Hair", 0x123456);
            check("color Hair", probe.transform.colorTransform.color == 0x123456,
                probe.transform.colorTransform.color.toString(16));
            stage.setPlayerColor("Hair", before);
            check("ui", stage.status != null && stage.status.parent == stage, "no status line");
            if (stage.armorError == null) skip("armor error shown", "the armor's code did not stop");
            else check("armor error shown", stage.status.text.indexOf(stage.armorError) >= 0, stage.status.text);
            return true;
        }

        private var skill:Object;

        private function playSkill():Boolean {
            var slots:Array = stage.settings.skills[stage.gender] as Array;
            skill = slots != null && slots.length > 0 ? slots[0] : null;
            if (skill == null || skill.armor == null) {
                skill = null;
                skip("skill", "the armor takes no skill label");
                return true;
            }
            stage.avatar.playLabel(skill.game);
            return true;
        }

        private function waitSkill():Boolean {
            if (skill == null) return true;
            if (stage.face.currentLabel == skill.armor) {
                check("skill " + skill.game, true);
                return true;
            }
            if (++waited < 3) return false;
            check("skill " + skill.game, false, "the head is on " + stage.face.currentLabel);
            skill = null;
            return true;
        }

        private function waitIdle():Boolean {
            if (skill == null) return true;
            if (stage.face.currentLabel == idleAnimation()) {
                check("back to Idle", true);
                return true;
            }
            if (++waited < 300) return false;
            check("back to Idle", false, "still on " + stage.face.currentLabel + " after 300 frames");
            return true;
        }

        private function done():Boolean {
            stage.log("DONE");
            return true;
        }
    }
}
